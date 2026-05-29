"""
Résumé IA des Cahiers des Conditions de Vente (CCV).
Utilise Claude avec prompt caching pour réduire les coûts.
"""
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

SYSTEM_PROMPT = """Tu es un expert en droit immobilier français, spécialisé dans les ventes judiciaires.
Tu analyses des Cahiers des Conditions de Vente (CCV) pour des marchands de biens et investisseurs.

Retourne UNIQUEMENT un JSON valide avec cette structure exacte :
{
  "occupant": {
    "is_occupied": boolean,
    "details": "statut occupant en 1 phrase"
  },
  "charges_copro": {
    "montant_mensuel": float ou null,
    "details": "description charges"
  },
  "procedures": ["procédure 1", "procédure 2"],
  "servitudes": ["servitude 1"],
  "etat_bien": "description état du bien en 2-3 phrases",
  "frais_prealables": {
    "montant": float ou null,
    "details": "description frais préalables à l'adjudication"
  },
  "points_vigilance": ["point 1", "point 2", "point 3"],
  "points_forts": ["point 1", "point 2"],
  "resume_global": "résumé en 2-3 phrases pour l'acheteur potentiel"
}

Règles :
- points_vigilance : 3 à 6 éléments critiques pour l'acheteur (occupation, dettes, travaux, droits...)
- points_forts : 1 à 3 avantages (si identifiables)
- Si une info est absente, utilise null ou []
- Réponds UNIQUEMENT avec le JSON brut, sans markdown ni texte autour"""


def _extract_pdf_text(pdf_path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("Package manquant : pip install pdfplumber")

    with pdfplumber.open(pdf_path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages[:30]]
    text = "\n".join(p for p in pages if p.strip())
    return text[:50_000]


def _download_pdf(url: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        r = httpx.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        f.write(r.content)
        return f.name


def _call_claude(text: str, model: str = "claude-sonnet-4-6") -> dict:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Package manquant : pip install anthropic")

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": f"Analyse ce Cahier des Conditions de Vente :\n\n{text}",
        }],
    )
    raw = msg.content[0].text.strip()

    # Strip markdown code fences if present
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if m:
        raw = m.group(1)

    return json.loads(raw)


def summarize_ccv(
    auction_id: str,
    pdf_url: Optional[str] = None,
    pdf_path: Optional[str] = None,
    force: bool = False,
    model: str = "claude-sonnet-4-6",
) -> Optional[dict]:
    """
    Génère le résumé IA d'un CCV et le stocke en base.
    Retourne le dict résumé, ou None si pas de PDF disponible.
    """
    from .db import db_session
    from .models import DocumentSummary

    with db_session() as session:
        existing = session.query(DocumentSummary).filter_by(auction_id=auction_id).first()
        if existing and not force:
            logger.info("Résumé existant pour {} — skip (force=True pour recalculer)", auction_id)
            return json.loads(existing.summary_json)

    if pdf_path:
        text = _extract_pdf_text(pdf_path)
    elif pdf_url:
        logger.info("Téléchargement CCV : {}", pdf_url)
        local = _download_pdf(pdf_url)
        text = _extract_pdf_text(local)
    else:
        logger.warning("Pas de PDF disponible pour l'enchère {}", auction_id)
        return None

    if not text.strip():
        logger.warning("PDF vide ou illisible pour {}", auction_id)
        return None

    logger.info("Analyse CCV ({} chars) — enchère {}", len(text), auction_id)
    summary = _call_claude(text, model=model)

    with db_session() as session:
        rec = session.query(DocumentSummary).filter_by(auction_id=auction_id).first()
        if rec:
            rec.summary_json = json.dumps(summary, ensure_ascii=False)
            rec.generated_at = datetime.utcnow()
            rec.model_version = model
        else:
            session.add(DocumentSummary(
                auction_id=auction_id,
                summary_json=json.dumps(summary, ensure_ascii=False),
                model_version=model,
                pdf_url=pdf_url,
            ))

    logger.success("Résumé CCV stocké pour {}", auction_id)
    return summary
