
from fastapi import FastAPI

app = FastAPI(
    title="ARSOFT Backend API",
    description="API del asistente de automoción ARSOFT",
    version="0.1.0",
)

@app.get("/health", tags=["Operación"])
async def health():
    return {"status": "ok"}
