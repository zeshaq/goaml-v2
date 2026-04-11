import base64
import os
import tempfile
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="nemotron-ocr-v2")

ocr_model = None
ocr_mode = "lazy"


def _build_model():
    import torch

    global ocr_mode

    if not torch.cuda.is_available():
        ocr_mode = "tesseract_fallback"
        return None

    from nemotron_ocr.inference.pipeline import NemotronOCR

    ocr_mode = "cuda"
    return NemotronOCR()


def get_model():
    global ocr_model
    if ocr_model is None:
        ocr_model = _build_model()
    return ocr_model


def format_predictions(predictions, output_format: str) -> str:
    texts = [str(item.get("text", "")).strip() for item in predictions if str(item.get("text", "")).strip()]
    if not texts:
        return ""
    if output_format == "markdown":
        return "\n\n".join(f"- {text}" for text in texts)
    return "\n".join(texts)


def run_tesseract(image_path: str, output_format: str) -> str:
    import pytesseract
    from PIL import Image

    text = pytesseract.image_to_string(Image.open(image_path)).strip()
    if output_format == "markdown":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(f"- {line}" for line in lines)
    return text


class OCRRequest(BaseModel):
    image_base64: str
    mime_type: Optional[str] = "image/png"
    output_format: Optional[str] = "markdown"


class OCRResponse(BaseModel):
    text: str
    format: str
    mode: str


@app.get("/health")
def health():
    return {"status": "ok", "mode": ocr_mode}


@app.post("/extract", response_model=OCRResponse)
def extract(req: OCRRequest):
    try:
        model = get_model()
        image_bytes = base64.b64decode(req.image_base64)
        suffix = ".png" if "png" in (req.mime_type or "") else ".jpg"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(image_bytes)
            tmp_path = f.name

        try:
            output_format = req.output_format or "text"
            if model is None:
                result = run_tesseract(tmp_path, output_format)
                return OCRResponse(text=result, format=output_format, mode=ocr_mode)

            try:
                predictions = model(tmp_path, merge_level="paragraph")
                result = format_predictions(predictions, output_format)
                return OCRResponse(text=result, format=output_format, mode=ocr_mode)
            except Exception:
                result = run_tesseract(tmp_path, output_format)
                return OCRResponse(text=result, format=output_format, mode="tesseract_fallback")
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8021)
