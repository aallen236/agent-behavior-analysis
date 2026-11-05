from collections import Counter
import tiktoken
import numpy as np
import faiss
import re
import json
import openai
import events

client = openai.OpenAI()

TOP_K = 3

encoding = tiktoken.get_encoding("cl100k_base")

document_text = """
Accounts Receivable Policy

Customers are generally invoiced on Net 30 payment terms unless otherwise specified in the governing contract.

Payments received from customers must be applied to the correct open invoice. Remittance information should be reviewed before payment application.

If a payment has been received but remains unapplied, the accounts receivable team should investigate the payment reference, customer account, and invoice details before updating the transaction.

Past-due customer balances should be reviewed by the collections team. Follow-up should occur according to the aging status and customer relationship.

Customers with unresolved overdue balances may require additional approval before further credit is extended.

Customer credit balances may be applied against future invoices when appropriate. Refunds must follow the company's approval process.
"""


document_text_runbook = """
Invoice Integration Runbook

Invoice payloads are transmitted to the external API only after source records pass field-level validation, including confirmation that a valid customer identifier, invoice number, and line-item total are present on the record.

Requests that exceed the external service's payload-size limit will be rejected outright. Large embedded images or file attachments should be stripped from the payload and transmitted through the separate document-upload endpoint before the invoice request is retried.

Transient API timeouts and 5xx errors should be retried using bounded exponential backoff, with a maximum of four retry attempts. If all retries are exhausted without a successful response, the integration must stop retrying automatically rather than looping indefinitely.

When retries are exhausted for a given invoice, the record should be flagged for manual review and the on-call integration engineer should be alerted rather than the record being silently dropped.

Duplicate invoice records should be prevented by using a stable, unique source identifier on every request and enforcing idempotent processing on the receiving end, so that a retried request never creates a second invoice.

All integration activity, including validation failures, retries, and manual-review escalations, should be logged with enough detail to reconstruct what happened to a given invoice after the fact.
"""

def search(query, records = None, index = None, top_k=TOP_K):
    """Create embeddings of query and pass to search function, retrieving top_k results
    and return an object with score, chunk ID and the original document text"""

    if records == None:
        records = embed_records(build_records(chunk_by_paragraphs(document_text_runbook),document_id="INV-RUN", document_title= "Invoice Integration Runbook"))
    if index == None:
        index = build_index(records)
    
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )

    query_vector = np.array([response.data[0].embedding], dtype="float32")
    faiss.normalize_L2(query_vector)

    scores, indices = index.search(query_vector, top_k)

    return [
        {
            "score": float(score),
            "chunk_id": records[idx]["chunk_id"],
            "text": records[idx]["text"]
        }
        for score, idx in zip(scores[0], indices[0])
    ]


def build_index(records):
    """Uses the embedded records to create indexes. First create a normalized (values > 0 && < 1 ) matrix, then
    use inner product to """
    matrix = np.array([r["embedding"] for r in records], dtype="float32")
    faiss.normalize_L2(matrix)
    dimension = matrix.shape[1]
    idx = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
    idx.add(matrix)
    return idx

def embed_records(records):
    """Use the embeddings model to create embedding arrays for the given records. Takes all records from the source document
    and creates a numeric representation of their content"""
    texts = [r["text"] for r in records]
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )

    for r, item in zip(records, response.data):
        r["embedding"] = item.embedding
    return records


def format_context(results):
    """
    Turn retrieved chunks into a numbered context block
    the model can cite back to.
    """
    parts = []

    for result in results:
        parts.append(f"[{result['chunk_id']}] {result['text']}")

    return "\n\n".join(parts)

def count_tokens(text: str) -> int:
    """Counts the token length of a given text encoding"""
    return len(encoding.encode(text))

def chunk_by_paragraphs(
    text: str,
    max_tokens: int = 60
):
    """Takes given text and splits by text blocks, applying token-length limits and chunking accordingly"""
    paragraphs = [
        p.strip()
        for p in text.split("\n\n")
        if p.strip()
    ]

    chunks = []
    current_chunk = []
    current_tokens = 0

    for paragraph in paragraphs:

        paragraph_tokens = count_tokens(paragraph)

        # If the paragraph itself is too large,
        # handle it separately.
        if paragraph_tokens > max_tokens:

            # Save anything we've already accumulated.
            if current_chunk:
                chunks.append(
                    "\n\n".join(current_chunk)
                )

                current_chunk = []
                current_tokens = 0

            # Fall back to token-based splitting
            # for this oversized paragraph.
            paragraph_chunks = split_large_paragraph(
                paragraph,
                max_tokens=max_tokens
            )

            chunks.extend(paragraph_chunks)
            continue

        # Would adding this paragraph exceed the ceiling?
        if (
            current_chunk
            and current_tokens + paragraph_tokens > max_tokens
        ):
            chunks.append(
                "\n\n".join(current_chunk)
            )

            current_chunk = []
            current_tokens = 0

        current_chunk.append(paragraph)
        current_tokens += paragraph_tokens

    # Don't forget the last chunk.
    if current_chunk:
        chunks.append(
            "\n\n".join(current_chunk)
        )

    return chunks

def split_large_paragraph(
    paragraph: str,
    max_tokens: int = 80,
    overlap: int = 50
):
    """Helper function used with chunking. Applies max_token and overlap rules to generate a list of document chunks"""
    tokens = encoding.encode(paragraph)

    chunks = []

    start = 0

    while start < len(tokens):

        end = start + max_tokens

        chunk_tokens = tokens[start:end]

        chunks.append(
            encoding.decode(chunk_tokens)
        )

        start += max_tokens - overlap

    return chunks


def build_records(chunk_texts, document_id,document_title):
    """Use the referenced document text to build a dictionary to use for encoding
    Chunk texts are the result of the chunking function. Paragraph, fixed window, etc."""
    return [
        {
            "document_id": document_id,
            "document_title": document_title,
            "chunk_id": f"{document_id}-{i}",
            "text": text
        }
        for i, text in enumerate(chunk_texts)
    ]

def keyword_score(answer: str, must_include: list[str]) -> dict:
    """Validation function to check for presence of required keywords in each answer"""
    answer_lower = answer.lower()
    hits = [term for term in must_include if term.lower() in answer_lower]

    return {
        "hits": hits,
        "misses": [t for t in must_include if t not in hits],
        "coverage": len(hits) / len(must_include)
    }
