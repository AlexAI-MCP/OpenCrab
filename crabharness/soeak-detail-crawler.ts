import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';

type RawStatus = 'pending' | 'processing' | 'done' | 'error';
type Division = 'goods' | 'construction' | 'service' | 'foreign' | string | null;

interface PendingCaseRow {
  bid_ntce_no: string;
  bid_ntce_ord: string;
  division: Division;
  ntce_nm: string | null;
  presmpt_prce: number | null;
  winner_nm: string | null;
  winner_bizno: string | null;
  winner_rate: number | null;
  winner_amt: number | null;
  prtcpt_cnum: number | null;
  rl_openg_dt: string | null;
  sucsf_bid_lwlt_rate: number | null;
  week_key: string | null;
  ntce_instt_nm: string | null;
  dminstt_nm: string | null;
  pub_prcrmnt_clsfc_nm: string | null;
  openg_dt: string | null;
  bssamt: number | null;
  listing_presmpt_prce: number | null;
  _track_raw_status?: boolean;
}

interface WorkProgressRow {
  bidPbancNo: string;
  bidPbancOrd: string;
  bidClsfNo: string;
  bidPrgrsOrd: string;
  prcmBsneSeCd: string;
  bidPgst: string;
  bidPrgrsDt?: string;
  onbsPrnmntDt?: string;
  realOnbsDt?: string;
  [key: string]: unknown;
}

interface BidderRow {
  rank: number | null;
  bidderNm: string;
  bidderBizno: string;
  bidRate: number | null;
  bidAmt: number | null;
  bidDt: string | null;
  reserveNoVal: string | null;
}

interface ReservePriceRow {
  seq: number;
  price: number | null;
  selected: number;
  drwtNum: number | null;
}

interface AnalysisCase {
  bid_ntce_no: string;
  bid_ntce_ord: string;
  ntce_nm: string | null;
  division: Division;
  presmpt_prce: number | null;
  bssamt: number | null;
  sucsf_bid_lwlt_rate: number | null;
  ntce_instt_nm: string | null;
  dminstt_nm: string | null;
  region: string;
  pub_prcrmnt_clsfc_nm: string | null;
  openg_dt: string | null;
  winner_nm: string | null;
  winner_bizno: string | null;
  winner_rate: number | null;
  winner_amt: number | null;
  prtcpt_cnum: number | null;
  actual_reserve_price: number | null;
  reserve_ratio: number | null;
  rate_p5: number | null;
  rate_p25: number | null;
  rate_p50: number | null;
  rate_p75: number | null;
  rate_p95: number | null;
  rate_min: number | null;
  rate_max: number | null;
  below_lwlt_pct: number | null;
  sweet_spot_pct: number | null;
  winner_margin: number | null;
  runner_up_rate: number | null;
  margin_to_runner_up: number | null;
}

interface CliOptions {
  limit?: number;
  bidNo?: string;
  bidOrd?: string;
  division?: Division;
  concurrency: number;
  delayMs: number;
  dryRun: boolean;
  includeProcessing: boolean;
}

const ROOT_DIR = process.cwd();
const WORKSPACE_DIR = resolve(join(ROOT_DIR, '_workspace'));
const DB_PATH = resolve(process.env.NARA_DB_PATH || join(ROOT_DIR, 'nara.db'));
const DEFAULT_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36';
const PROGRESS_PATH = resolve(process.env.SOEAK_PROGRESS_PATH || join(WORKSPACE_DIR, 'soeak-detail-crawler-progress.json'));
const ERROR_LOG_PATH = resolve(process.env.SOEAK_ERROR_LOG_PATH || join(WORKSPACE_DIR, 'soeak-detail-crawler-errors.ndjson'));

const BID_STATUS_LABELS: Record<string, string> = {
  입160004: '개찰완료',
  입160010: '개찰완료',
  입160005: '유찰',
  입160006: '재입찰',
  입160012: '입찰취소',
};

const REGION_PATTERNS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'] as const;
const REGION_ALIASES: Array<[RegExp, string]> = [
  [/경기도|경기특별자치도/, '경기'],
  [/강원도|강원특별자치도/, '강원'],
  [/충청북도/, '충북'],
  [/충청남도/, '충남'],
  [/전북특별자치도|전라북도/, '전북'],
  [/전라남도/, '전남'],
  [/경상북도/, '경북'],
  [/경상남도/, '경남'],
  [/제주특별자치도/, '제주'],
];

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = {
    concurrency: 5,
    delayMs: 300,
    dryRun: false,
    includeProcessing: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === '--limit' && next) {
      options.limit = Number.parseInt(next, 10);
      index += 1;
    } else if (arg === '--bid-no' && next) {
      options.bidNo = next.trim();
      index += 1;
    } else if (arg === '--bid-ord' && next) {
      options.bidOrd = next.trim();
      index += 1;
    } else if (arg === '--division' && next) {
      options.division = next.trim();
      index += 1;
    } else if (arg === '--concurrency' && next) {
      options.concurrency = Number.parseInt(next, 10);
      index += 1;
    } else if (arg === '--delay-ms' && next) {
      options.delayMs = Number.parseInt(next, 10);
      index += 1;
    } else if (arg === '--dry-run') {
      options.dryRun = true;
    } else if (arg === '--include-processing') {
      options.includeProcessing = true;
    }
  }

  if (!Number.isFinite(options.concurrency) || options.concurrency < 1) options.concurrency = 5;
  if (options.concurrency > 10) options.concurrency = 10;
  if (!Number.isFinite(options.delayMs) || options.delayMs < 0) options.delayMs = 300;
  if (options.limit !== undefined && (!Number.isFinite(options.limit) || options.limit < 1)) delete options.limit;

  return options;
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const parsed = Number.parseFloat(String(value).replace(/,/g, '').trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function toStringValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = decodeHtmlEntities(String(value)).trim();
  return text ? text : null;
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&#(\d+);/g, (_, digits) => String.fromCodePoint(Number.parseInt(digits, 10)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;|&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function cleanBizNo(value: string | null | undefined): string {
  return (value || '').replace(/\D/g, '');
}

function toStatusLabel(code: unknown): string {
  const normalized = toStringValue(code) || '';
  return BID_STATUS_LABELS[normalized] || normalized;
}

function round(value: number | null, digits = 3): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  const base = 10 ** digits;
  return Math.round(value * base) / base;
}

function quantile(sorted: number[], ratio: number): number | null {
  if (sorted.length === 0) return null;
  if (sorted.length === 1) return sorted[0] ?? null;
  const position = (sorted.length - 1) * ratio;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower] ?? null;
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function extractRegion(...values: Array<string | null | undefined>): string {
  const merged = values.filter(Boolean).join(' ');
  for (const region of REGION_PATTERNS) {
    if (merged.includes(region)) return region;
  }
  for (const [pattern, region] of REGION_ALIASES) {
    if (pattern.test(merged)) return region;
  }
  return '';
}

function normalizeRank(value: unknown, fallbackIndex: number): number | null {
  const numeric = toNumber(value);
  if (numeric === null) return fallbackIndex + 1;
  return Math.trunc(numeric);
}

function normalizeReserveSeq(value: unknown, fallbackIndex: number): number {
  const numeric = toNumber(value);
  if (numeric === null) return fallbackIndex + 1;
  return Math.trunc(numeric);
}

function selectBestWorkProgress(rows: WorkProgressRow[]): WorkProgressRow {
  return [...rows].sort((left, right) => {
    const leftDate = String(left.realOnbsDt || left.bidPrgrsDt || left.onbsPrnmntDt || '');
    const rightDate = String(right.realOnbsDt || right.bidPrgrsDt || right.onbsPrnmntDt || '');
    if (leftDate !== rightDate) return rightDate.localeCompare(leftDate);
    const leftOrd = Number.parseInt(String(left.bidPrgrsOrd || '0'), 10) || 0;
    const rightOrd = Number.parseInt(String(right.bidPrgrsOrd || '0'), 10) || 0;
    if (leftOrd !== rightOrd) return rightOrd - leftOrd;
    const leftClsf = Number.parseInt(String(left.bidClsfNo || '0'), 10) || 0;
    const rightClsf = Number.parseInt(String(right.bidClsfNo || '0'), 10) || 0;
    return rightClsf - leftClsf;
  })[0]!;
}

function analyzeCase(row: PendingCaseRow, bidders: BidderRow[], reservePrices: ReservePriceRow[]): AnalysisCase {
  const winnerRate = row.winner_rate ?? bidders[0]?.bidRate ?? null;
  const winnerAmt = row.winner_amt ?? bidders[0]?.bidAmt ?? null;
  const lwltRate = row.sucsf_bid_lwlt_rate ?? null;
  const presmptPrce = row.presmpt_prce ?? row.listing_presmpt_prce ?? null;
  const bssamt = row.bssamt ?? presmptPrce;
  const region = extractRegion(row.ntce_instt_nm, row.dminstt_nm);

  const sortedRates = bidders
    .map(item => item.bidRate)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .sort((left, right) => left - right);

  const belowLwltPct = lwltRate !== null && sortedRates.length
    ? round((sortedRates.filter(rate => rate < lwltRate).length / sortedRates.length) * 100, 1)
    : null;
  const sweetSpotPct = lwltRate !== null && sortedRates.length
    ? round((sortedRates.filter(rate => rate >= lwltRate && rate <= (lwltRate + 0.3)).length / sortedRates.length) * 100, 1)
    : null;

  const selectedPrices = reservePrices
    .filter(item => item.selected === 1)
    .map(item => item.price)
    .filter((value): value is number => value !== null && Number.isFinite(value));

  const actualReservePrice = selectedPrices.length
    ? Math.round(selectedPrices.reduce((sum, value) => sum + value, 0) / selectedPrices.length)
    : null;

  const reserveRatio = actualReservePrice !== null && bssamt !== null && bssamt !== 0
    ? actualReservePrice / bssamt
    : null;

  const runnerUp = bidders.find(item => item.rank === 2) || bidders[1] || null;
  const gapToRunnerUp = runnerUp && winnerRate !== null && runnerUp.bidRate !== null
    ? Math.abs(runnerUp.bidRate - winnerRate)
    : null;

  return {
    bid_ntce_no: row.bid_ntce_no,
    bid_ntce_ord: row.bid_ntce_ord,
    ntce_nm: row.ntce_nm,
    division: row.division,
    presmpt_prce: presmptPrce,
    bssamt,
    sucsf_bid_lwlt_rate: lwltRate,
    ntce_instt_nm: row.ntce_instt_nm,
    dminstt_nm: row.dminstt_nm,
    region,
    pub_prcrmnt_clsfc_nm: row.pub_prcrmnt_clsfc_nm,
    openg_dt: row.openg_dt || row.rl_openg_dt,
    winner_nm: row.winner_nm || bidders[0]?.bidderNm || null,
    winner_bizno: cleanBizNo(row.winner_bizno) || bidders[0]?.bidderBizno || null,
    winner_rate: winnerRate,
    winner_amt: winnerAmt,
    prtcpt_cnum: row.prtcpt_cnum ?? bidders.length,
    actual_reserve_price: actualReservePrice,
    reserve_ratio: round(reserveRatio, 6),
    rate_p5: round(quantile(sortedRates, 0.05), 3),
    rate_p25: round(quantile(sortedRates, 0.25), 3),
    rate_p50: round(quantile(sortedRates, 0.50), 3),
    rate_p75: round(quantile(sortedRates, 0.75), 3),
    rate_p95: round(quantile(sortedRates, 0.95), 3),
    rate_min: round(sortedRates[0] ?? null, 3),
    rate_max: round(sortedRates[sortedRates.length - 1] ?? null, 3),
    below_lwlt_pct: belowLwltPct,
    sweet_spot_pct: sweetSpotPct,
    winner_margin: lwltRate !== null && winnerRate !== null ? round(winnerRate - lwltRate, 3) : null,
    runner_up_rate: runnerUp?.bidRate !== null && runnerUp?.bidRate !== undefined ? round(runnerUp.bidRate, 3) : null,
    margin_to_runner_up: round(gapToRunnerUp, 3),
  };
}

function ensureTables(db: DatabaseSync) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS analysis_soeak_cases (
      bid_ntce_no TEXT PRIMARY KEY,
      bid_ntce_ord TEXT,
      ntce_nm TEXT,
      division TEXT,
      presmpt_prce REAL,
      bssamt REAL,
      sucsf_bid_lwlt_rate REAL,
      ntce_instt_nm TEXT,
      dminstt_nm TEXT,
      region TEXT,
      pub_prcrmnt_clsfc_nm TEXT,
      openg_dt TEXT,
      winner_nm TEXT,
      winner_bizno TEXT,
      winner_rate REAL,
      winner_amt REAL,
      prtcpt_cnum INTEGER,
      actual_reserve_price REAL,
      reserve_ratio REAL,
      rate_p5 REAL,
      rate_p25 REAL,
      rate_p50 REAL,
      rate_p75 REAL,
      rate_p95 REAL,
      rate_min REAL,
      rate_max REAL,
      below_lwlt_pct REAL,
      sweet_spot_pct REAL,
      winner_margin REAL,
      runner_up_rate REAL,
      margin_to_runner_up REAL,
      collected_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS analysis_soeak_bidders (
      bid_ntce_no TEXT NOT NULL,
      rank INTEGER,
      bidder_nm TEXT,
      bidder_bizno TEXT,
      bid_rate REAL,
      bid_amt REAL,
      drwt_no1 TEXT,
      drwt_no2 TEXT,
      bid_dt TEXT,
      PRIMARY KEY (bid_ntce_no, rank)
    );

    CREATE TABLE IF NOT EXISTS analysis_soeak_reserve_prices (
      bid_ntce_no TEXT NOT NULL,
      seq INTEGER,
      price REAL,
      selected INTEGER,
      drwt_num INTEGER,
      PRIMARY KEY (bid_ntce_no, seq)
    );
  `);
}

function openDb(): DatabaseSync {
  const db = new DatabaseSync(DB_PATH);
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec('PRAGMA foreign_keys = ON;');
  db.exec('PRAGMA busy_timeout = 5000;');
  ensureTables(db);
  return db;
}

function tableExists(db: DatabaseSync, tableName: string): boolean {
  const row = db.prepare(`
    SELECT name
    FROM sqlite_master
    WHERE type = 'table' AND name = ?
  `).get(tableName) as { name?: string } | undefined;
  return Boolean(row?.name);
}

function buildDirectTargetRow(options: CliOptions): PendingCaseRow[] {
  if (!options.bidNo) return [];
  return [
    {
      bid_ntce_no: options.bidNo,
      bid_ntce_ord: options.bidOrd || '000',
      division: options.division || 'service',
      ntce_nm: null,
      presmpt_prce: null,
      winner_nm: null,
      winner_bizno: null,
      winner_rate: null,
      winner_amt: null,
      prtcpt_cnum: null,
      rl_openg_dt: null,
      sucsf_bid_lwlt_rate: null,
      week_key: null,
      ntce_instt_nm: null,
      dminstt_nm: null,
      pub_prcrmnt_clsfc_nm: null,
      openg_dt: null,
      bssamt: null,
      listing_presmpt_prce: null,
      _track_raw_status: false,
    },
  ];
}

function selectPendingRows(db: DatabaseSync, options: CliOptions): PendingCaseRow[] {
  const rawTableAvailable = tableExists(db, 'analysis_soeak_raw');
  if (!rawTableAvailable) {
    return buildDirectTargetRow(options);
  }

  const whereClause = options.bidNo
    ? 'raw.bid_ntce_no = ?'
    : `raw.status IN (${options.includeProcessing ? `'pending','processing'` : `'pending'`})`;

  const params: Array<string | number> = [];
  if (options.bidNo) params.push(options.bidNo);

  let sql = `
    SELECT
      raw.bid_ntce_no,
      COALESCE(raw.bid_ntce_ord, '000') AS bid_ntce_ord,
      COALESCE(raw.division, pl.division, ar.division, 'service') AS division,
      COALESCE(raw.ntce_nm, pl.ntce_nm) AS ntce_nm,
      raw.presmpt_prce,
      raw.winner_nm,
      raw.winner_bizno,
      raw.winner_rate,
      raw.winner_amt,
      raw.prtcpt_cnum,
      raw.rl_openg_dt,
      raw.sucsf_bid_lwlt_rate,
      raw.week_key,
      pl.ntce_instt_nm,
      COALESCE(pl.dminstt_nm, ar.dminstt_nm) AS dminstt_nm,
      pl.pub_prcrmnt_clsfc_nm,
      COALESCE(pl.openg_dt, raw.rl_openg_dt) AS openg_dt,
      pl.bssamt,
      pl.presmpt_prce AS listing_presmpt_prce
    FROM analysis_soeak_raw raw
    LEFT JOIN procurement_listings pl
      ON pl.bid_ntce_no = raw.bid_ntce_no AND pl.bid_ntce_ord = COALESCE(raw.bid_ntce_ord, '000')
    LEFT JOIN award_results ar
      ON ar.bid_ntce_no = raw.bid_ntce_no AND ar.bid_ntce_ord = COALESCE(raw.bid_ntce_ord, '000')
    WHERE ${whereClause}
    ORDER BY raw.collected_at ASC, raw.bid_ntce_no ASC
  `;

  if (options.limit) {
    sql += ' LIMIT ?';
    params.push(options.limit);
  }

  const rows = db.prepare(sql).all(...params) as PendingCaseRow[];
  if (rows.length === 0 && options.bidNo) {
    return buildDirectTargetRow(options);
  }
  return rows.map(row => ({ ...row, _track_raw_status: true }));
}

function claimCase(db: DatabaseSync, row: PendingCaseRow): boolean {
  const result = db.prepare(`
    UPDATE analysis_soeak_raw
    SET status = 'processing'
    WHERE bid_ntce_no = ? AND bid_ntce_ord = ? AND status IN ('pending', 'processing')
  `).run(row.bid_ntce_no, row.bid_ntce_ord);
  return Number(result.changes) > 0;
}

function markStatus(db: DatabaseSync, row: Pick<PendingCaseRow, 'bid_ntce_no' | 'bid_ntce_ord'>, status: RawStatus) {
  db.prepare(`
    UPDATE analysis_soeak_raw
    SET status = ?
    WHERE bid_ntce_no = ? AND bid_ntce_ord = ?
  `).run(status, row.bid_ntce_no, row.bid_ntce_ord);
}

function persistSuccess(
  db: DatabaseSync,
  row: PendingCaseRow,
  analysis: AnalysisCase,
  bidders: BidderRow[],
  reservePrices: ReservePriceRow[],
) {
  const clearBidders = db.prepare('DELETE FROM analysis_soeak_bidders WHERE bid_ntce_no = ?');
  const clearReserve = db.prepare('DELETE FROM analysis_soeak_reserve_prices WHERE bid_ntce_no = ?');
  const upsertCase = db.prepare(`
    INSERT OR REPLACE INTO analysis_soeak_cases (
      bid_ntce_no, bid_ntce_ord, ntce_nm, division, presmpt_prce, bssamt, sucsf_bid_lwlt_rate,
      ntce_instt_nm, dminstt_nm, region, pub_prcrmnt_clsfc_nm, openg_dt,
      winner_nm, winner_bizno, winner_rate, winner_amt, prtcpt_cnum,
      actual_reserve_price, reserve_ratio,
      rate_p5, rate_p25, rate_p50, rate_p75, rate_p95, rate_min, rate_max,
      below_lwlt_pct, sweet_spot_pct, winner_margin, runner_up_rate, margin_to_runner_up,
      collected_at
    ) VALUES (
      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime')
    )
  `);
  const insertBidder = db.prepare(`
    INSERT OR REPLACE INTO analysis_soeak_bidders (
      bid_ntce_no, rank, bidder_nm, bidder_bizno, bid_rate, bid_amt, drwt_no1, drwt_no2, bid_dt
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const insertReserve = db.prepare(`
    INSERT OR REPLACE INTO analysis_soeak_reserve_prices (
      bid_ntce_no, seq, price, selected, drwt_num
    ) VALUES (?, ?, ?, ?, ?)
  `);

  db.exec('BEGIN IMMEDIATE;');
  try {
    upsertCase.run(
      analysis.bid_ntce_no,
      analysis.bid_ntce_ord,
      analysis.ntce_nm,
      analysis.division,
      analysis.presmpt_prce,
      analysis.bssamt,
      analysis.sucsf_bid_lwlt_rate,
      analysis.ntce_instt_nm,
      analysis.dminstt_nm,
      analysis.region,
      analysis.pub_prcrmnt_clsfc_nm,
      analysis.openg_dt,
      analysis.winner_nm,
      analysis.winner_bizno,
      analysis.winner_rate,
      analysis.winner_amt,
      analysis.prtcpt_cnum,
      analysis.actual_reserve_price,
      analysis.reserve_ratio,
      analysis.rate_p5,
      analysis.rate_p25,
      analysis.rate_p50,
      analysis.rate_p75,
      analysis.rate_p95,
      analysis.rate_min,
      analysis.rate_max,
      analysis.below_lwlt_pct,
      analysis.sweet_spot_pct,
      analysis.winner_margin,
      analysis.runner_up_rate,
      analysis.margin_to_runner_up,
    );

    clearBidders.run(row.bid_ntce_no);
    for (const bidder of bidders.slice(0, 100)) {
      insertBidder.run(
        row.bid_ntce_no,
        bidder.rank,
        bidder.bidderNm,
        bidder.bidderBizno,
        bidder.bidRate,
        bidder.bidAmt,
        null,
        bidder.reserveNoVal,
        bidder.bidDt,
      );
    }

    clearReserve.run(row.bid_ntce_no);
    for (const reserve of reservePrices) {
      insertReserve.run(row.bid_ntce_no, reserve.seq, reserve.price, reserve.selected, reserve.drwtNum);
    }

    if (row._track_raw_status !== false) {
      markStatus(db, row, 'done');
    }
    db.exec('COMMIT;');
  } catch (error) {
    db.exec('ROLLBACK;');
    throw error;
  }
}

function writeProgress(payload: Record<string, unknown>) {
  mkdirSync(dirname(PROGRESS_PATH), { recursive: true });
  writeFileSync(PROGRESS_PATH, JSON.stringify({ updated_at: new Date().toISOString(), ...payload }, null, 2), 'utf-8');
}

function appendError(payload: Record<string, unknown>) {
  mkdirSync(dirname(ERROR_LOG_PATH), { recursive: true });
  appendFileSync(ERROR_LOG_PATH, `${JSON.stringify({ at: new Date().toISOString(), ...payload })}\n`, 'utf-8');
}

class G2BWorker {
  private readonly context: BrowserContext;
  private readonly page: Page;
  private readonly onbsPopupId: string;
  private readonly rsvePopupId: string;
  private lastStartedAt = 0;

  private constructor(context: BrowserContext, page: Page, index: number) {
    this.context = context;
    this.page = page;
    this.onbsPopupId = `soeakOnbs${index}`;
    this.rsvePopupId = `soeakRsve${index}`;
  }

  static async create(browser: Browser, index: number): Promise<G2BWorker> {
    const context = await browser.newContext({ userAgent: DEFAULT_UA });
    const page = await context.newPage();
    await page.goto('https://www.g2b.go.kr/', { waitUntil: 'networkidle', timeout: 120000 });
    await sleep(5000);

    const worker = new G2BWorker(context, page, index);
    await worker.ensurePopupLoaded('PBOC007_01', worker.onbsPopupId, '개찰결과');
    await worker.ensurePopupLoaded('PBOC024_01', worker.rsvePopupId, '예비가격산정결과');
    return worker;
  }

  async close() {
    await this.context.close();
  }

  private async ensurePopupLoaded(menuCangVal: string, popupId: string, popupName: string) {
    await this.page.evaluate(({ menuCangVal, popupId, popupName }) => {
      const existing = Boolean((window as Record<string, unknown>)[`${popupId}_wframe_popupCnts_scwin`]);
      if (!existing) {
        com.gfnOpenPopup({ menuCangVal, popupId, popupName, width: 1280, height: 960, param: {} });
      }
    }, { menuCangVal, popupId, popupName });

    await this.page.waitForFunction(
      (id) => Boolean((window as Record<string, unknown>)[`${id}_wframe_popupCnts_scwin`]),
      popupId,
      { timeout: 60000 },
    );

    await sleep(1000);
  }

  async throttle(delayMs: number) {
    const now = Date.now();
    const waitMs = Math.max(0, this.lastStartedAt + delayMs - now);
    if (waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs));
    this.lastStartedAt = Date.now();
  }

  async fetchWorkProgress(bidNo: string, bidOrd: string): Promise<WorkProgressRow[]> {
    const result = await this.page.evaluate(async ({ bidNo, bidOrd }) => {
      const response = await fetch('/fi/fiu/fiua/UntySrch/srchWorkPrgs.do', {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json;charset=UTF-8',
          submissionid: 'srchWorkPrgs',
        },
        body: JSON.stringify({ dlWorkParamM: { workSrchSeCd: 'BK', workBizNo: bidNo, workBizOrd: bidOrd } }),
        credentials: 'include',
      });

      return { status: response.status, json: await response.json() };
    }, { bidNo, bidOrd });

    if (result.status !== 200) {
      throw new Error(`srchWorkPrgs failed (${result.status})`);
    }

    const rows = Array.isArray(result.json?.dlWorkPrgsL) ? result.json.dlWorkPrgsL : [];
    return rows as WorkProgressRow[];
  }

  async fetchBidders(progress: WorkProgressRow, preferredDivision: Division): Promise<BidderRow[]> {
    const plans = this.buildBidderPlans(progress, preferredDivision);
    let lastError = 'no bidder plan succeeded';

    for (const plan of plans) {
      const result = await this.page.evaluate(async ({ popupId, plan }) => {
        const scope = window as Record<string, any>;
        const prefix = `${popupId}_wframe_popupCnts_`;
        const input = scope[`${prefix}dlSrchOnbsRsltBidInM`];
        const scwin = scope[`${prefix}scwin`];
        const list = scope[`${prefix}${plan.listName}`];

        input.set('bidPbancNo', plan.bidPbancNo);
        input.set('bidPbancOrd', plan.bidPbancOrd);
        input.set('bidClsfNo', plan.bidClsfNo);
        input.set('bidPrgrsOrd', plan.bidPrgrsOrd);
        input.set('prcmBsneSeCd', plan.prcmBsneSeCd);
        input.set('bidPgstCd', plan.bidPgstCd);
        input.set('bzmnRegNo', '');
        input.set('reOpenPbancYN', '');

        try {
          await scwin[plan.fnName](1);
          return { ok: true, rows: list.getAllJSON() as Array<Record<string, unknown>> };
        } catch (error) {
          return { ok: false, error: String(error) };
        }
      }, { popupId: this.onbsPopupId, plan });

      if (!result.ok) {
        lastError = result.error;
        continue;
      }

      if (!Array.isArray(result.rows) || result.rows.length === 0) {
        lastError = `${plan.fnName}: empty`;
        continue;
      }

      return result.rows.map((item, index): BidderRow => ({
        rank: normalizeRank(item.onbsRnkg ?? item.rowNum ?? item.itemNo, index),
        bidderNm: toStringValue(item.grpNm ?? item.spplEtpsNm ?? item.makrNm) || '',
        bidderBizno: cleanBizNo(toStringValue(item.bzmnRegNo)),
        bidRate: toNumber(item.bdrt ?? item.bdngItrt),
        bidAmt: toNumber(item.bdngAmt),
        bidDt: toStringValue(item.slprRcptnDt ?? item.hopeQty ?? item.inptDt),
        reserveNoVal: toStringValue(item.rsvePrceNoVal),
      })).sort((left, right) => (left.rank ?? 999999) - (right.rank ?? 999999));
    }

    throw new Error(lastError);
  }

  async fetchReservePrices(progress: WorkProgressRow): Promise<ReservePriceRow[]> {
    const result = await this.page.evaluate(async ({ popupId, progress }) => {
      const scope = window as Record<string, any>;
      const prefix = `${popupId}_wframe_popupCnts_`;
      const input = scope[`${prefix}dlSrchPbancInfoInM`];
      const scwin = scope[`${prefix}scwin`];
      const list = scope[`${prefix}dlRsvePrceOutL`];

      input.set('bidPbancNo', progress.bidPbancNo);
      input.set('bidPbancOrd', progress.bidPbancOrd);
      input.set('bidClsfNo', progress.bidClsfNo);
      input.set('bidPrgrsOrd', progress.bidPrgrsOrd);
      input.set('prcmBsneSeCd', progress.prcmBsneSeCd);
      input.set('blffVrfcYn', '');

      try {
        await scwin.fnRsvePrceInfoInq();
        return { ok: true, rows: list.getAllJSON() as Array<Record<string, unknown>> };
      } catch (error) {
        return { ok: false, error: String(error) };
      }
    }, { popupId: this.rsvePopupId, progress });

    if (!result.ok) throw new Error(result.error);

    const selectedSeqs = new Set<number>();
    for (const item of result.rows) {
      if (String(item.etpsDrawYn1 ?? '') === 'Y') selectedSeqs.add(normalizeReserveSeq(item.plrlRsvePrceSqno1, 0));
      if (String(item.etpsDrawYn2 ?? '') === 'Y') selectedSeqs.add(normalizeReserveSeq(item.plrlRsvePrceSqno2, 1));
    }

    const flat: ReservePriceRow[] = [];
    for (const item of result.rows) {
      const leftSeq = normalizeReserveSeq(item.plrlRsvePrceSqno1, flat.length);
      flat.push({
        seq: leftSeq,
        price: toNumber(item.plrlRsvePrce1),
        selected: selectedSeqs.has(leftSeq) ? 1 : 0,
        drwtNum: toNumber(item.drawNotm1),
      });

      const rightSeq = normalizeReserveSeq(item.plrlRsvePrceSqno2, flat.length);
      flat.push({
        seq: rightSeq,
        price: toNumber(item.plrlRsvePrce2),
        selected: selectedSeqs.has(rightSeq) ? 1 : 0,
        drwtNum: toNumber(item.drawNotm2),
      });
    }

    return flat.filter(item => item.price !== null).sort((left, right) => left.seq - right.seq);
  }

  private buildBidderPlans(progress: WorkProgressRow, preferredDivision: Division) {
    const base = {
      bidPbancNo: String(progress.bidPbancNo || ''),
      bidPbancOrd: String(progress.bidPbancOrd || ''),
      bidClsfNo: String(progress.bidClsfNo || ''),
      bidPrgrsOrd: String(progress.bidPrgrsOrd || ''),
      prcmBsneSeCd: String(progress.prcmBsneSeCd || ''),
      bidPgstCd: toStatusLabel(progress.bidPgst),
    };

    const ordered: Array<{ fnName: string; listName: string }> = [];
    const push = (fnName: string, listName: string) => {
      if (!ordered.some(item => item.fnName === fnName)) ordered.push({ fnName, listName });
    };

    const division = String(preferredDivision || '');
    if (division === 'construction') push('fnSbidCstn', 'dlOnbsRsltSbidCstnOutL');
    if (division === 'service') push('fnSbidSrvc', 'dlOnbsRsltSbidSrvcOutL');
    if (division === 'goods') push('fnSbidGods', 'dlOnbsRsltSbidGodsOutL');
    if (division === 'foreign') push('fnSbidFrcp', 'dlOnbsRsltSbidFrcpOutL');

    push('fnSbidCstn', 'dlOnbsRsltSbidCstnOutL');
    push('fnSbidSrvc', 'dlOnbsRsltSbidSrvcOutL');
    push('fnSbidGods', 'dlOnbsRsltSbidGodsOutL');
    push('fnSbidFrcp', 'dlOnbsRsltSbidFrcpOutL');
    push('fnSbidLase', 'dlOnbsRsltSbidLaseOutL');
    push('fnSbidRsrv', 'dlOnbsRsltSbidRsrvOutL');

    return ordered.map(item => ({ ...base, ...item }));
  }
}

async function main() {
  mkdirSync(dirname(PROGRESS_PATH), { recursive: true });
  mkdirSync(dirname(ERROR_LOG_PATH), { recursive: true });

  const options = parseArgs(process.argv.slice(2));
  const db = openDb();
  const rows = selectPendingRows(db, options);

  if (rows.length === 0) {
    console.log('No matching rows.');
    writeProgress({ total: 0, done: 0, error: 0, message: 'no matching rows' });
    db.close();
    return;
  }

  console.log(`Selected ${rows.length} case(s); concurrency=${options.concurrency}; delayMs=${options.delayMs}; dryRun=${options.dryRun}`);
  writeProgress({ total: rows.length, done: 0, error: 0, current: null });

  const browser = await chromium.launch({
    headless: true,
  });
  const workers: G2BWorker[] = [];

  try {
    for (let index = 0; index < options.concurrency; index += 1) {
      workers.push(await G2BWorker.create(browser, index + 1));
      console.log(`Worker ${index + 1}/${options.concurrency} ready`);
    }

    let nextIndex = 0;
    let doneCount = 0;
    let errorCount = 0;

    const workLoop = async (worker: G2BWorker, workerIndex: number) => {
      while (true) {
        const row = rows[nextIndex];
        nextIndex += 1;
        if (!row) return;

        await worker.throttle(options.delayMs);
        const label = `${row.bid_ntce_no}-${row.bid_ntce_ord}`;
        writeProgress({ total: rows.length, done: doneCount, error: errorCount, current: label, worker: workerIndex });
        console.log(`[worker ${workerIndex}] start ${label}`);

        if (!options.dryRun && row._track_raw_status !== false && !claimCase(db, row)) {
          console.log(`[worker ${workerIndex}] skip ${label} (claim failed)`);
          continue;
        }

        try {
          const workRows = await worker.fetchWorkProgress(row.bid_ntce_no, row.bid_ntce_ord);
          if (workRows.length === 0) throw new Error('no work progress rows');

          const selected = selectBestWorkProgress(workRows);
          const bidders = await worker.fetchBidders(selected, row.division);
          const reservePrices = await worker.fetchReservePrices(selected);
          const analysis = analyzeCase(row, bidders, reservePrices);

          if (!options.dryRun) {
            persistSuccess(db, row, analysis, bidders, reservePrices);
          }

          doneCount += 1;
          console.log(`[worker ${workerIndex}] done ${label} bidders=${bidders.length} reserve=${reservePrices.length}`);
        } catch (error) {
          errorCount += 1;
          const message = error instanceof Error ? error.message : String(error);
          appendError({ bid_ntce_no: row.bid_ntce_no, bid_ntce_ord: row.bid_ntce_ord, error: message });
          if (!options.dryRun && row._track_raw_status !== false) markStatus(db, row, 'error');
          console.error(`[worker ${workerIndex}] error ${label}: ${message}`);
        } finally {
          writeProgress({ total: rows.length, done: doneCount, error: errorCount, current: label, worker: workerIndex });
        }
      }
    };

    await Promise.all(workers.map((worker, index) => workLoop(worker, index + 1)));
    writeProgress({ total: rows.length, done: doneCount, error: errorCount, current: null, message: 'complete' });
    console.log(`Complete: done=${doneCount}, error=${errorCount}, total=${rows.length}`);
  } finally {
    await Promise.allSettled(workers.map(worker => worker.close()));
    await browser.close();
    db.close();
  }
}

main().catch(error => {
  const message = error instanceof Error ? `${error.message}\n${error.stack || ''}` : String(error);
  appendError({ fatal: true, error: message });
  writeProgress({ fatal: true, error: message });
  console.error(message);
  process.exitCode = 1;
});
