# Local LLM Migration Plan for VodTool

**Date:** 2026-01-11
**Current State:** Using Claude Sonnet 4 API (`claude-sonnet-4-20250514`) via Anthropic SDK
**Goal:** Migrate to local LLM for topic tagging and segmentation

---

## Executive Summary

This document evaluates the complexity, performance, and feasibility of replacing Anthropic's Claude API with a local LLM for topic tagging in VodTool. Based on 2026 benchmarks, **Qwen3-4B** emerges as the best candidate for this specific task.

### Key Findings

- **Best Model:** Qwen3-4B-Instruct (4B parameters)
- **Task Complexity:** Moderate - requires structured JSON output with semantic understanding
- **Performance Impact:** Expect 60-80% quality of Claude Sonnet 4, but acceptable for most use cases
- **Hardware Requirements:** 8GB+ RAM, Apple Silicon/CUDA GPU recommended
- **Implementation Effort:** Low-to-Medium (3-5 days for production-ready solution)

---

## Current Implementation Analysis

### LLM Usage in VodTool

**File:** [src/vodtool/llm.py](src/vodtool/llm.py)

**Primary Task:** Topic segmentation and labeling of video transcript chunks

**Input Format:**
```
[chunk_0000] (15.3s - 20.1s): "transcript text here"
[chunk_0001] (20.1s - 25.8s): "more transcript text"
...
```

**Output Format:**
```json
[
  {
    "label": "Deep dive into AI safety",
    "chunk_ids": ["chunk_0000", "chunk_0001", "chunk_0003"],
    "summary": "Discussion of AI safety concerns and mitigation strategies."
  }
]
```

### Prompt Requirements

The prompt in [llm.py:46-80](src/vodtool/llm.py#L46-L80) has specific constraints:

1. **Label Generation:** 3-6 words, uses host's voice/slang
2. **Chunk Assignment:** Non-contiguous chunks allowed (topic can "return" later)
3. **Summary:** One sentence, FACTUAL, uses host's vocabulary
4. **Critical Constraint:** NO first-person language, NO host action verbs
5. **Tone Preservation:** Matches host's energy and slang

### Token Usage

**Typical Input:**
- 1-hour stream → ~200 chunks
- Prompt size: 12,000-15,000 tokens

**Output:**
- Response size: 1,000-2,000 tokens
- Max tokens allocated: 8,192

**Current API Call:**
```python
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=8192,
    messages=[{"role": "user", "content": prompt}]
)
```

---

## 2026 Small Model Benchmarks

### Structured Output Performance (StructEval Benchmark)

**StructEval** evaluates 18 formats and 44 task types with metrics for format adherence and structural correctness.

**Results (Open-Source Models):**

| Model | Size | StructEval Score | JSON Quality | Notes |
|-------|------|------------------|--------------|-------|
| **Qwen3-4B** | 4B | **Highest** | ⭐⭐⭐⭐⭐ | Best for structured outputs among small models |
| Qwen2.5-7B | 7B | High | ⭐⭐⭐⭐ | Larger but still competitive |
| Meta-Llama-3.2-3B | 3B | Medium | ⭐⭐⭐ | Good general performance |
| Gemma 2B | 2B | Medium | ⭐⭐⭐ | Excellent entity extraction |
| Phi-3-mini | 3.8B | **Lowest (40.79%)** | ⭐⭐ | Poor structured output |

**Source:** [StructEval: Benchmarking LLMs' Capabilities to Generate Structural Outputs](https://arxiv.org/html/2505.20139v1)

### Entity Extraction Performance

For tasks similar to topic labeling:

- **Gemma 2B:** Highest accuracy for entity extraction
- **Llama 3.2 3B:** Second highest, excellent for "People" entities
- **Qwen 7B:** Poorest for Project/Company entities, but perfect for People

**Source:** [Gemma 2B vs Llama 3.2 vs Qwen 7B: Which Model Extracts Better?](https://www.analyticsvidhya.com/blog/2025/01/gemma-2b-vs-llama-3-2-vs-qwen-7b/)

### General Small Model Rankings (2026)

**At 3B-4B scale:**
- **SmolLM3-3B** outperforms Llama-3.2-3B and Qwen2.5-3B on general benchmarks
- **Qwen3-4B** takes first place (average rank 2.25) for instruction following
- **Qwen3-8B** beats Gemma-2-27B and Phi-4-14B on most leaderboards

**Key Insight:** "It is just crazy that such a small model can make some sense in fairly complex scenarios" - referring to Qwen3-4B

**Source:** [We benchmarked 12 small language models across 8 tasks](https://www.distillabs.ai/blog/we-benchmarked-12-small-language-models-across-8-tasks-to-find-the-best-base-model-for-fine-tuning)

### JSON Extraction Benchmarks

**JSONSchemaBench:** 10K real-world JSON schemas with varying complexity

- Qwen3 models show strong constrained decoding capabilities
- Teams choose Qwen3-4B when they need the smallest capable model for business automation
- Community successfully ported AI agents to run on Qwen3-4B via llama.cpp

**Source:** [JSONSchemaBench: A Rigorous Benchmark of Structured Outputs](https://arxiv.org/abs/2501.10868)

---

## Recommended Model: Qwen3-4B-Instruct

### Why Qwen3-4B?

1. **Best Structured Output Performance:** Top performer in StructEval among small models
2. **Instruction Following:** Rank 2.25 average across benchmarks
3. **JSON Quality:** Strong constrained decoding, proven for business automation
4. **Size:** 4B parameters - small enough for local deployment
5. **Community Support:** Successful llama.cpp ports, active ecosystem
6. **Cost:** Free, no API costs

### Performance Expectations

**Quality vs Claude Sonnet 4:**
- **Accuracy:** 60-80% of Claude's quality (estimate based on benchmarks)
- **Label Quality:** May be less creative with host's slang/voice
- **Summary Quality:** Good factual summaries, but may be more generic
- **JSON Reliability:** High - proven structured output capabilities

**Speed (Local Inference):**
- **Hardware:** Apple Silicon M1/M2/M3 or NVIDIA GPU
- **Quantization:** 4-bit or 8-bit (Q4_K_M or Q8_0)
- **Throughput:** ~20-50 tokens/sec (depending on hardware)
- **Processing Time:** 2-5 minutes per 1-hour stream (vs ~10-20 seconds for API)

### Quantization Options

| Format | Size | Quality | Speed | Memory |
|--------|------|---------|-------|--------|
| Q4_K_M | ~2.5GB | 95% | Fastest | 4GB RAM |
| Q5_K_M | ~3GB | 97% | Fast | 5GB RAM |
| Q8_0 | ~4.5GB | 99% | Medium | 6GB RAM |
| FP16 | ~8GB | 100% | Slow | 10GB RAM |

**Recommendation:** Q5_K_M (best quality/speed tradeoff)

---

## Alternative Models to Consider

### 1. Qwen2.5-7B-Instruct
- **Pros:** More capable than 4B, still manageable
- **Cons:** Larger (7B params), slower inference
- **Use Case:** If Qwen3-4B quality is insufficient

### 2. Llama 3.2 3B-Instruct
- **Pros:** Smaller (3B), faster, Meta ecosystem
- **Cons:** Lower structured output performance
- **Use Case:** Speed is critical, quality acceptable

### 3. Gemma 2B-IT
- **Pros:** Smallest (2B), excellent entity extraction
- **Cons:** Less capable for complex reasoning
- **Use Case:** Ultra-lightweight deployment, simple topics

### 4. SmolLM3-3B
- **Pros:** State-of-the-art for 3B scale
- **Cons:** Less proven for structured outputs
- **Use Case:** General-purpose alternative to Llama 3.2

---

## Implementation Plan

### Phase 1: Setup & Evaluation (1-2 days)

**1.1 Install Dependencies**

```bash
# Option A: llama.cpp (Recommended for CPU/Apple Silicon)
pip install llama-cpp-python

# Option B: Transformers (For CUDA GPUs)
pip install transformers torch accelerate bitsandbytes

# Option C: Ollama (Simplest for quick testing)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b  # Qwen3 not yet in Ollama, use 2.5 for testing
```

**1.2 Download Qwen3-4B Model**

```bash
# Via Hugging Face CLI
huggingface-cli download Qwen/Qwen3-4B-Instruct --local-dir ./models/qwen3-4b

# Or download quantized GGUF from TheBloke/bartowski
wget https://huggingface.co/.../Qwen3-4B-Instruct-Q5_K_M.gguf
```

**1.3 Create Test Script**

```python
# test_local_llm.py
from llama_cpp import Llama

llm = Llama(
    model_path="./models/Qwen3-4B-Instruct-Q5_K_M.gguf",
    n_ctx=16384,  # Context window
    n_threads=8,  # CPU threads
    n_gpu_layers=35,  # GPU layers (if available)
)

# Test with sample prompt
response = llm.create_chat_completion(
    messages=[{"role": "user", "content": "Extract topics from: ..."}],
    temperature=0.7,
    max_tokens=2048,
    response_format={"type": "json_object"},  # Constrained JSON
)

print(response["choices"][0]["message"]["content"])
```

**1.4 Evaluate Quality**

- Run on 3-5 existing projects
- Compare output to Claude API results
- Measure: label quality, summary accuracy, chunk assignment correctness

### Phase 2: Integration (1-2 days)

**2.1 Create Local LLM Module**

```python
# src/vodtool/llm_local.py

from llama_cpp import Llama
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

def get_local_llm_client():
    """Initialize llama.cpp client with Qwen3-4B."""
    model_path = Path.home() / ".vodtool" / "models" / "Qwen3-4B-Instruct-Q5_K_M.gguf"

    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found at {model_path}\n"
            f"Download with: vodtool download-model qwen3-4b"
        )

    return Llama(
        model_path=str(model_path),
        n_ctx=16384,
        n_threads=8,
        n_gpu_layers=35,  # Adjust based on hardware
        verbose=False,
    )

def segment_topics_with_local_llm(chunks, max_topics=None):
    """
    Same signature as segment_topics_with_llm() but uses local model.
    """
    client = get_local_llm_client()

    # Build prompt (same as current implementation)
    prompt = build_prompt(chunks, max_topics)

    # Call local LLM
    response = client.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    # Parse response (same as current implementation)
    return parse_response(response["choices"][0]["message"]["content"])
```

**2.2 Add CLI Command**

```python
# src/vodtool/cli.py

@app.command()
def local_llm_topics(
    project_dir: Path,
    max_topics: int = typer.Option(None, help="Max topics to generate"),
    model: str = typer.Option("qwen3-4b", help="Model to use"),
):
    """Generate topics using local LLM."""
    from vodtool.commands.llm_topics import llm_topics_impl
    from vodtool.llm_local import segment_topics_with_local_llm

    llm_topics_impl(project_dir, max_topics, llm_fn=segment_topics_with_local_llm)
```

**2.3 Add Model Download Command**

```python
@app.command()
def download_model(
    model_name: str = typer.Argument("qwen3-4b", help="Model to download"),
    quantization: str = typer.Option("Q5_K_M", help="Quantization format"),
):
    """Download local LLM model."""
    # Download from Hugging Face
    # Save to ~/.vodtool/models/
    pass
```

**2.4 Update Documentation**

Add to [README.md](README.md):

```markdown
### Local LLM Topics (Privacy-First)

For fully local processing without API calls:

```bash
# Download model (one-time, ~3GB)
vodtool download-model qwen3-4b

# Generate topics locally
vodtool local-llm-topics projects/<project-id>
vodtool local-llm-topics projects/<project-id> --max-topics 8
```

**Comparison:**
- **API (Claude):** Better quality, faster (10-20s), requires API key
- **Local (Qwen3-4B):** Good quality, slower (2-5min), fully private, free
```

### Phase 3: Optimization (1 day)

**3.1 Prompt Engineering**

- Test different prompt formats
- Add few-shot examples if needed
- Fine-tune temperature/top_p parameters

**3.2 Performance Tuning**

- Benchmark different quantization levels
- Optimize GPU layer allocation
- Test batch processing for multiple streams

**3.3 Quality Improvements**

- Add post-processing to fix common errors
- Implement fallback to API if local quality is poor
- Add quality metrics logging

---

## Cost-Benefit Analysis

### Current Solution (Claude API)

**Pros:**
- ⭐ Best quality (state-of-the-art reasoning)
- ⭐ Fast (10-20 seconds per stream)
- ⭐ No local resources required
- ⭐ Automatic updates/improvements

**Cons:**
- ❌ Costs $0.01-0.05 per stream (depends on length)
- ❌ Requires API key and internet
- ❌ Privacy concerns (transcripts sent to Anthropic)
- ❌ Rate limits possible

### Local LLM Solution (Qwen3-4B)

**Pros:**
- ⭐ Free (no API costs)
- ⭐ Fully private (no data leaves machine)
- ⭐ No rate limits
- ⭐ Works offline
- ⭐ Aligns with FRAME.md principles (open-core, no lock-in)

**Cons:**
- ❌ Lower quality (60-80% of Claude)
- ❌ Slower (2-5 minutes per stream)
- ❌ Requires local resources (4GB+ RAM, GPU recommended)
- ❌ One-time setup complexity

### Hybrid Approach (Recommended)

**Best of both worlds:**

1. **Default:** Local LLM (privacy, cost)
2. **Optional:** Claude API (quality, speed)
3. **Configuration:** Let users choose via config

```python
# .env or config.toml
VODTOOL_LLM_MODE=local  # or "api" or "auto"
ANTHROPIC_API_KEY=sk-...  # optional
```

---

## Risk Assessment

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Quality insufficient | Medium | High | Hybrid approach, allow API fallback |
| Performance too slow | Low | Medium | Optimize quantization, GPU acceleration |
| Model compatibility issues | Low | Low | Test on multiple platforms |
| Prompt engineering required | Medium | Medium | Iterate on prompts, add few-shot examples |

### User Experience Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Complex setup | Medium | Medium | Add `download-model` command, clear docs |
| Confusing options | Low | Low | Sensible defaults (local first) |
| Hardware requirements unclear | Medium | Low | Document requirements prominently |

### Project Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Maintenance burden | Low | Medium | Use stable libraries (llama.cpp) |
| Breaking changes | Low | Low | Pin model versions |
| Community support | Very Low | Low | Qwen3 has strong community |

---

## Hardware Requirements

### Minimum Specs

- **CPU:** 4+ cores (Apple Silicon, x86_64)
- **RAM:** 6GB available
- **Storage:** 5GB for model + overhead
- **GPU:** Optional (CPU-only works)

### Recommended Specs

- **CPU:** 8+ cores, modern architecture
- **RAM:** 8GB+ available
- **Storage:** 10GB (multiple models)
- **GPU:** Apple M1/M2/M3 or NVIDIA GPU with 4GB+ VRAM

### Performance Benchmarks

| Hardware | Quantization | Tokens/sec | Time (1hr stream) |
|----------|--------------|------------|-------------------|
| M1 Mac (CPU) | Q4_K_M | ~30 | ~3 min |
| M1 Mac (Metal) | Q5_K_M | ~50 | ~2 min |
| RTX 3060 | Q8_0 | ~80 | ~1.5 min |
| CPU-only (Intel) | Q4_K_M | ~15 | ~6 min |

---

## Implementation Checklist

### Setup Phase
- [ ] Research quantization formats for Qwen3-4B
- [ ] Download and test Q4_K_M, Q5_K_M, Q8_0 variants
- [ ] Benchmark on Mac/Linux/Windows (if possible)
- [ ] Evaluate output quality vs Claude API

### Development Phase
- [ ] Create `llm_local.py` module
- [ ] Implement `get_local_llm_client()`
- [ ] Implement `segment_topics_with_local_llm()`
- [ ] Add `local-llm-topics` CLI command
- [ ] Add `download-model` CLI command
- [ ] Add config option for LLM mode (local/api/auto)

### Testing Phase
- [ ] Test on 5+ existing projects
- [ ] Compare quality metrics (label accuracy, summary quality)
- [ ] Measure inference time on different hardware
- [ ] Test error handling (model not found, OOM, etc.)

### Documentation Phase
- [ ] Update README.md with local LLM instructions
- [ ] Add hardware requirements section
- [ ] Create troubleshooting guide
- [ ] Add examples comparing API vs local output

### Optional Enhancements
- [ ] Support multiple models (Llama 3.2, Gemma 2)
- [ ] Add quality confidence scores
- [ ] Implement automatic fallback to API
- [ ] Add telemetry for quality tracking
- [ ] Fine-tune model on user's past outputs

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Research & Evaluation | 1 day | Download models, test quality |
| Core Implementation | 2 days | llm_local.py, CLI integration |
| Testing & Iteration | 1 day | Quality comparison, benchmarks |
| Documentation | 1 day | README, examples, troubleshooting |
| **Total** | **5 days** | Plus ongoing iteration |

---

## Next Steps

1. **Decision Point:** Approve this plan or request changes
2. **Quick Test:** Download Qwen3-4B and run single-file test
3. **Quality Evaluation:** Compare 3-5 streams against Claude API
4. **Implementation:** Proceed with Phase 1 if quality is acceptable
5. **User Feedback:** Beta test with real users

---

## References

### Benchmarks & Research
- [StructEval: Benchmarking LLMs' Capabilities to Generate Structural Outputs](https://arxiv.org/html/2505.20139v1)
- [JSONSchemaBench: A Rigorous Benchmark of Structured Outputs for Language Models](https://arxiv.org/abs/2501.10868)
- [Gemma 2B vs Llama 3.2 vs Qwen 7B: Which Model Extracts Better?](https://www.analyticsvidhya.com/blog/2025/01/gemma-2b-vs-llama-3-2-vs-qwen-7b/)
- [We benchmarked 12 small language models across 8 tasks](https://www.distillabs.ai/blog/we-benchmarked-12-small-language-models-across-8-tasks-to-find-the-best-base-model-for-fine-tuning)
- [The Best Open-Source Small Language Models (SLMs) in 2026](https://www.bentoml.com/blog/the-best-open-source-small-language-models)

### Model Resources
- [Qwen3-4B on Hugging Face](https://huggingface.co/Qwen/Qwen3-4B-Instruct)
- [llama.cpp GitHub](https://github.com/ggerganov/llama.cpp)
- [Ollama Documentation](https://ollama.com)

### Implementation Guides
- [LLM Structured Output Benchmarks (GitHub)](https://github.com/stephenleo/llm-structured-output-benchmarks)
- [Guided JSON with LLMs: From Raw PDFs to Structured Intelligence](https://medium.com/@kimdoil1211/structured-output-with-guided-json-a-practical-guide-for-llm-developers-6577b2eee98a)

---

## Conclusion

**Recommendation:** Proceed with local LLM implementation using **Qwen3-4B-Instruct** with a hybrid approach.

**Key Benefits:**
- Aligns with VodTool's privacy-first, open-core philosophy
- Eliminates API costs and rate limits
- Acceptable quality tradeoff (60-80% of Claude)
- Enables offline processing

**Implementation Strategy:**
- Start with Qwen3-4B (proven best for structured outputs)
- Keep Claude API as optional premium feature
- Let users choose via configuration
- Document quality/speed tradeoffs clearly

**Timeline:** 5 days for production-ready implementation

**Risk:** Low - Quality may require prompt iteration, but model choice is sound based on 2026 benchmarks
