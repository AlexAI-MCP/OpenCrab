"""Ontology engine: builder, ReBAC, impact analysis, and hybrid query."""

from opencrab.ontology.builder import OntologyBuilder
from opencrab.ontology.impact import ImpactEngine
from opencrab.ontology.query import HybridQuery
from opencrab.ontology.rebac import ReBACEngine

__all__ = ["OntologyBuilder", "ReBACEngine", "ImpactEngine", "HybridQuery"]
