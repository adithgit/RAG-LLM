import os

# Reduce allocator fragmentation before importing torch (helps peak RSS during model load).
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

import gc
import torch
import logging
import sys
import time
from flask import Flask, request, jsonify, g
from flask_cors import CORS

from llama_index.core import VectorStoreIndex, Document, Settings, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.huggingface import HuggingFaceLLM
from llama_index.core.prompts.prompts import SimpleInputPrompt
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import fitz  # PyMuPDF
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

# Set up structured JSON logging for ELK stack
import json

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, 'service', "lawracle-backend"),
        }
        
        # Merge any extra kwargs passed to the logger (like our request details)
        if hasattr(record, 'method'):
            log_record['method'] = record.method
        if hasattr(record, 'path'):
            log_record['path'] = record.path
        if hasattr(record, 'status'):
            log_record['status'] = record.status
        if hasattr(record, 'duration_ms'):
            log_record['duration_ms'] = record.duration_ms
        if hasattr(record, 'client_ip'):
            log_record['client_ip'] = record.client_ip
        if hasattr(record, 'query_text'):
            log_record['query_text'] = record.query_text
            
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
handlers = [handler]

# Ship logs directly to Logstash via TCP if available (set LOGSTASH_DISABLE=1 to skip when Logstash is down)
LOGSTASH_HOST = os.getenv('LOGSTASH_HOST', '')
LOGSTASH_PORT = int(os.getenv('LOGSTASH_PORT', '5044'))
if LOGSTASH_HOST and os.getenv('LOGSTASH_DISABLE', '').lower() not in ('1', 'true', 'yes'):
    try:
        from logstash_async.handler import AsynchronousLogstashHandler
        logstash_handler = AsynchronousLogstashHandler(
            LOGSTASH_HOST, LOGSTASH_PORT, database_path=None
        )
        # Fix: Apply the custom JSON formatter to the Logstash connection
        logstash_handler.setFormatter(JsonFormatter())
        handlers.append(logstash_handler)
    except Exception as e:
        print(f"Warning: Could not connect to Logstash at {LOGSTASH_HOST}:{LOGSTASH_PORT} - {e}")

logging.basicConfig(level=logging.INFO, handlers=handlers)
logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# --- MIDDLEWARE FOR REQUEST/RESPONSE LOGGING ---
@app.before_request
def start_timer():
    # Start a stopwatch the moment the request hits the server
    g.start_time = time.time()

@app.after_request
def log_request_response(response):
    # Calculate how long the request took
    duration = time.time() - g.start_time if hasattr(g, 'start_time') else 0

    # Skip logging for the /health endpoint to avoid spamming Kibana
    if request.path == '/health':
        return response

    # Gather all the request and response details
    log_data = {
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": round(duration * 1000, 2),
        "client_ip": request.remote_addr,
    }

    # If you want to log the specific question the user asked
    if request.path == '/query' and request.is_json:
        try:
            # Safely try to get the query without breaking the request
            log_data["query_text"] = request.get_json(silent=True).get('query', '')
        except Exception:
            pass

    # Log as an error if it's a 4xx or 5xx status code
    if response.status_code >= 400:
        logger.error(f"{request.method} {request.path} failed", extra=log_data)
    else:
        logger.info(f"{request.method} {request.path} completed", extra=log_data)

    return response

# Environment paths for containerized deployment
DATA_DIR = os.getenv('DATA_DIR', './data')
CHROMA_DB_PATH = os.getenv('CHROMA_DB_PATH', './chroma_db')
# If downloading from HuggingFace, you can use "TinyLlama/TinyLlama-1.1B-Chat-v1.0" for lightweight CPU runs.
# For cached volumes, point to the mount path.
LLM_MODEL_NAME = os.getenv('LLM_MODEL_NAME', 'TinyLlama/TinyLlama-1.1B-Chat-v1.0')

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CHROMA_DB_PATH, exist_ok=True)

query_engine = None

def extract_text_from_pdf(pdf_path):
    try:
        text = ""
        with fitz.open(pdf_path) as doc:
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {str(e)}")
        return ""

def load_and_process_documents():
    logger.info("Loading documents...")
    documents = []
    
    if not os.path.exists(DATA_DIR):
        return []

    files = [f for f in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, f))]

    for filename in files:
        file_path = os.path.join(DATA_DIR, filename)
        try:
            if filename.lower().endswith('.pdf'):
                text = extract_text_from_pdf(file_path)
                if not text.strip():
                    continue
            elif filename.lower().endswith(('.txt', '.md')):
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            else:
                continue

            documents.append(Document(text=text, metadata={"source": filename}))
            logger.info(f"Loaded {filename}")
        except Exception as e:
            logger.error(f"Error processing {filename}: {str(e)}")

    return documents

def create_vector_index(documents, embed_model, chroma_collection):
    logger.info(f"Creating vector index from {len(documents)} documents...")
    text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
    
    nodes = []
    for doc in documents:
        nodes.extend(text_splitter.get_nodes_from_documents([doc]))

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(nodes, storage_context=storage_context)
    return index

def truncate_text(text, max_words=200):
    words = text.split()
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + "..."

def format_leap_response(query, raw_response):
    if "Legal Issue" in raw_response and "Action Steps" in raw_response:
        if len(raw_response.split()) <= 400:
            return raw_response

    query_lower = query.lower()
    if any(word in query_lower for word in ["accident", "crash", "collision"]):
        issue = "a motor vehicle accident and potential liability under road safety laws"
    elif any(word in query_lower for word in ["property", "land", "tenant", "owner"]):
        issue = "a property dispute or real estate matter"
    elif any(word in query_lower for word in ["marriage", "divorce", "custody"]):
        issue = "a family law matter"
    else:
        issue = "a potential legal concern requiring professional advice"

    truncated_response = truncate_text(str(raw_response), 150)

    formatted_response = f"""
**Legal Issue**:
This query concerns {issue}.

**Explanation of Law**:
{truncated_response}

**Action Steps**:
1. Consult with a qualified legal professional specializing in this area of law
2. Gather all relevant documentation and evidence related to your case
3. Consider filing appropriate paperwork with relevant authorities

**Practical Guidance**:
Maintain thorough documentation of all events, communications, and expenses related to this matter.
"""
    return formatted_response

def setup_rag_system():
    global query_engine
    logger.info("Initializing RAG pipeline...")
    # Fewer CPU threads can lower peak memory from OpenMP/BLAS during load on small nodes.
    torch.set_num_threads(int(os.getenv("TORCH_CPU_NUM_THREADS", "1")))

    system_prompt = """
You are Lawracle, an AI legal assistant specializing in Indian law.

STRICT RULES:
- Answer ONLY using information explicitly stated in the provided context documents.
- Do NOT invent, assume, or add legal provisions, punishments, or section numbers not present in the context.
- If the context lacks information, state: 'The available documents do not contain specific information on this point.'
- Always cite exact section numbers and act names as found in the context.

Use the L.E.A.P. structure:
1. Legal Issue: 1-2 sentences identifying the core legal problem.
2. Explanation of Law: 2-3 sentences citing only what the context states.
3. Action Steps: 2-3 practical steps.
4. Practical Guidance: 1-2 tips.

Keep your TOTAL response strictly under 150 words.
"""
    query_wrapper_prompt = SimpleInputPrompt(
        "<|system|>\n" + system_prompt.strip() + "</s>\n<|user|>\n{query_str}</s>\n<|assistant|>\n"
    )

    logger.info(f"Loading Model: {LLM_MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME, use_fast=False)

    if torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL_NAME,
            quantization_config=bnb_config,
            device_map="auto",
            torch_dtype=torch.float16,
        )
    elif torch.backends.mps.is_available():
        logger.info("Apple Silicon GPU (MPS) detected! Using Metal for accelerated inference.")
        model = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL_NAME,
            device_map="mps",
            torch_dtype=torch.float16,
        )
    else:
        logger.warning("No GPU found! Loading model on CPU with float16 to reduce memory usage.")
        model = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL_NAME,
            device_map="cpu",
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        )
    gc.collect()

    embed_model = HuggingFaceEmbedding(
        model_name="all-MiniLM-L6-v2",
        device="cpu"
    )

    llm = HuggingFaceLLM(
        model_name=LLM_MODEL_NAME,
        model=model,
        tokenizer=tokenizer,
        context_window=2048,
        max_new_tokens=100,
        query_wrapper_prompt=query_wrapper_prompt,
        generate_kwargs={"temperature": 0.2, "do_sample": True},
    )

    Settings.llm = llm
    Settings.embed_model = embed_model
    Settings.chunk_size = 512
    Settings.chunk_overlap = 50

    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    chroma_collection = chroma_client.get_or_create_collection("lawracle_docs")

    if chroma_collection.count() > 0:
        logger.info(f"Loaded existing ChromaDB ({chroma_collection.count()} chunks)")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store)
    else:
        documents = load_and_process_documents()
        if not documents:
            documents = [Document(text="Sample legal text.", metadata={"source": "sample"})]
        index = create_vector_index(documents, embed_model, chroma_collection)

    query_engine = index.as_query_engine(
        response_mode="compact",
        similarity_top_k=2,
    )
    logger.info("RAG pipeline ready.")

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "model": "lawracle", "ready": query_engine is not None})

@app.route('/query', methods=['POST'])
def process_query():
    if not query_engine:
        return jsonify({"error": "Pipeline initializing"}), 503

    data = request.json
    if not data or 'query' not in data:
        return jsonify({"error": "No query provided"}), 400

    query = data['query']
    
    try:
        raw_response = query_engine.query(query)
        formatted_response = format_leap_response(query, str(raw_response))
        return jsonify({"response": formatted_response})
    except Exception as e:
        # We don't need logger.error here since the @app.after_request middleware 
        # will catch the 500 error and log it automatically!
        return jsonify({"response": format_leap_response(query, "Unable to retrieve specific information.")}), 500

# Endpoint to capture logs sent from the frontend UI
@app.route('/log', methods=['POST'])
def receive_frontend_log():
    data = request.json
    # Log it as an error, but let Kibana know it came from the frontend UI
    logger.error(f"Frontend UI Error: {data.get('message')}", extra={"service": "lawracle-frontend-ui"})
    return jsonify({"status": "logged"})

import threading

# Start initialization in background so Gunicorn binds instantly and doesn't timeout
threading.Thread(target=setup_rag_system, daemon=True).start()

if __name__ == '__main__':
    # In production, use Gunicorn instead of app.run
    app.run(host='0.0.0.0', port=5000, use_reloader=False)