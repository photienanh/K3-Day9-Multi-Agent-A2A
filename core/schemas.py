from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class RankedCause(BaseModel):
    cause_code: str
    rank: int

class ResponsibleParty(BaseModel):
    party_type: str
    party_id: str

class RootCauseAnalysis(BaseModel):
    ranked_causes: List[RankedCause]
    responsible_parties: List[ResponsibleParty]

class Assessment(BaseModel):
    primary_issue: str
    case_status: str  # action_required or no_action
    confidence: float

class AffectedEntities(BaseModel):
    order_ids: List[str]
    item_ids: List[str]
    seller_ids: List[str]
    payment_ids: List[str]

class FinancialResolution(BaseModel):
    currency: str = "BRL"
    item_total_brl: float
    freight_total_brl: float
    payment_total_brl: float
    recommended_refund_brl: float

class OutputSchema(BaseModel):
    case_id: str
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: List[str]
    financial_resolution: FinancialResolution
    resolution_actions: List[str]
