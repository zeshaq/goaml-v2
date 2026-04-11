import os
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uvicorn

app = FastAPI(title="aml-scorer")

model = None

def get_model():
    global model
    if model is None:
        import xgboost as xgb
        model_path = "/models/aml_scorer.json"
        if not os.path.exists(model_path):
            raise RuntimeError(f"Model not found at {model_path}")
        model = xgb.Booster()
        model.load_model(model_path)
    return model

class ScoreRequest(BaseModel):
    features: List[List[float]]

class ScoreResponse(BaseModel):
    scores: List[float]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    try:
        import xgboost as xgb
        m = get_model()
        X = np.array(req.features, dtype=np.float32)
        dmatrix = xgb.DMatrix(X)
        preds = m.predict(dmatrix).tolist()
        return ScoreResponse(scores=preds)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
