import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn

app = FastAPI(title="gliner-pii")

gliner_model = None

DEFAULT_ENTITIES = [
    "person", "organization", "location", "email", "phone", "address",
    "date", "ssn", "credit_card", "bank_account", "passport", "license_plate",
    "ip_address", "url", "username", "password", "national_id", "tax_id",
    "medical_record", "drug", "disease", "age", "gender", "nationality",
    "religion", "political_party", "financial_info", "salary", "company_reg"
]

def get_model():
    global gliner_model
    if gliner_model is None:
        from gliner import GLiNER
        gliner_model = GLiNER.from_pretrained("nvidia/gliner-PII")
    return gliner_model

class PIIRequest(BaseModel):
    text: str
    entities: Optional[List[str]] = None
    threshold: Optional[float] = 0.5

class PIIEntity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: float

class PIIResponse(BaseModel):
    entities: List[PIIEntity]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/extract", response_model=PIIResponse)
def extract(req: PIIRequest):
    try:
        model = get_model()
        entity_types = req.entities or DEFAULT_ENTITIES
        results = model.predict_entities(
            req.text,
            entity_types,
            threshold=req.threshold
        )
        entities = [
            PIIEntity(
                text=e["text"],
                label=e["label"],
                start=e["start"],
                end=e["end"],
                score=e["score"]
            )
            for e in results
        ]
        return PIIResponse(entities=entities)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
