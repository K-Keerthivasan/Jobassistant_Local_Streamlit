# Lane 3 | AI and automation

NOC 21232, 21211, 21223. Priority lane, and the lane carrying his single strongest differentiator. Read `00-index.md` for the Status conventions and tier rules.

**PR note.** All three codes are TEER 1, which feeds Express Entry's Canadian Experience Class cleanly. 21232 is on the North Bay RCIP list. AIP covers the lane entirely, and Ontario's Workforce Priority stream takes any of them with a qualifying offer. The entry bar for this lane stays deliberately generous because the differentiator is real.

## NOC map

| NOC | Title | TEER | When it applies |
|---|---|---|---|
| 21232 | Software developers and programmers | 1 | The default for AI engineer, GenAI developer and Python automation seats where the work is building software. |
| 21211 | Data scientists | 1 | Only where the posting genuinely asks for modelling and experimentation. Do not stretch into it from prompt and pipeline work. |
| 21223 | Database analysts and data administrators | 1 | RAG and vector-store work that is substantially data architecture. |

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Python | The working language of the lane | held | Automation pipelines, scrapers, and the local AI tooling. |
| LLM application development | Prompting, context design, output structuring, evaluation | held | The local Node.js plus Hermes on Ollama pipeline, and the resume generation and outreach automation built on it. |
| Workflow automation platforms | n8n, Zapier, Make. n8n is the one most often named in Canadian postings | held | n8n-automation-master repo, the K2 Automation Hub, and the job application pipeline. This is the deepest thing on the list. |
| API integration | REST, JSON, auth, rate limits, error handling and retries | held | Every pipeline he runs is API-driven end to end. K2_Press publishes multi-brand social through Postiz over API. |
| Node.js and JavaScript | The other working language of the lane | held | K2 client builds, K2_Press, the local generation app. |
| Prompt engineering | Structured prompting, system design, reliability under variation | held | Production use across the resume generation and outreach pipelines, not a demo. |
| Self-hosting and local models | Running models locally, resource and throughput trade-offs | held | Hermes on Ollama, running as part of the working pipeline rather than an experiment. |
| Git and version control | Projects, branching, documentation | held | Four maintained public repos. |

## Important

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| RAG pipelines | Chunking, embeddings, vector stores, retrieval quality | partial | Retrieval and context assembly inside his own pipelines. Not a tuned production RAG system with measured retrieval quality. |
| Agent orchestration and MCP | Multi-step agents, tool use, MCP servers | partial | Working knowledge through the Claude and n8n toolchain. Worth marking `held` once a public repo shows it. |
| AI-assisted development tooling | Copilot, Cursor, Claude Code named explicitly in postings | held | Daily working toolchain. |
| Cloud basics | AWS, Azure or GCP enough to deploy and run what he builds | partial | Deployment experience through Firebase and Supabase. Not a major cloud provider at platform level. |
| Docker | Containerising a service | partial | Self-hosting setup involves it; depth not evidenced. |
| Evaluation and testing of LLM output | Measuring quality rather than eyeballing it | not yet | This is the gap that separates hobby pipelines from production ones, and postings are starting to name it. |

## Optional

| Skill | Note | Status |
|---|---|---|
| ML fundamentals | Enough to talk about training, fine-tuning and when not to | partial |
| Vector databases by name | Pinecone, Weaviate, pgvector | not yet |
| LangChain or LlamaIndex | Named in a minority of postings; the concepts transfer from what he already builds | partial |

## Later

| Skill | Note | Status |
|---|---|---|
| Model fine-tuning | Beyond prompting, into training | not yet |
| MLOps | Deployment, monitoring and versioning of models | not yet |

## Not required

Research-level machine learning, publications, a graduate degree in ML. A posting requiring those is a data scientist seat, not this lane.

## Honest positioning

This is the lane where he is genuinely ahead of the field for his experience level. Most junior candidates have used an LLM. He has built and operated pipelines that do real work on a schedule, self-hosted a model, and shipped automation that other people's work depends on. That is a portfolio argument, not a resume-bullet argument, so lead with the repos and the systems, not with adjectives.

Most postings in this lane grade Tier A or Tier B. The honest gap is **evaluation**: he can build the pipeline, and he cannot yet show he measured whether it was any good. Closing that with a documented eval on one existing pipeline would be a small amount of work for a large credibility gain, and it is also the thing that makes QA lane 1 and this lane reinforce each other.

## Interview watch

Expect to be asked what broke and how you found it. Pipeline work interviews well when the answer is specific about a failure: a rate limit, a malformed payload, a prompt that drifted. Have two of those ready. Expect also "how do you know the output is correct", which is the evaluation gap, so answer it honestly and say what you would put in place.

## Sourcing vocabulary

- **Core:** ai engineer, ai developer, automation engineer, llm engineer, genai developer, ai automation specialist, agentic ai, prompt engineer, ai solutions developer, ai integration developer.
- **Tool-anchored, high signal:** n8n developer, langchain developer, openai developer, python automation developer, make.com specialist.
- **Adjacent, worth opening:** integration developer, workflow automation specialist, rpa developer, ml engineer, automation specialist.

## Aliases

Alternate names the grader matches against posting text, one line per skill. The skill name before the colon must match a row in the tables above.

- Python: python, python 3, python scripting, python development
- LLM application development: llm, llms, large language models, generative ai, genai, openai, gpt, claude, gemini, llm applications, ai applications, chatbots, copilots, ai assistants
- Workflow automation platforms: n8n, zapier, make, make.com, integromat, power automate, workflow automation, automation platforms, low-code automation
- API integration: rest api, apis, api integration, json, webhooks, oauth, http apis, integrations, third-party apis
- Node.js and JavaScript: node.js, nodejs, javascript, typescript, node
- Prompt engineering: prompt engineering, prompting, prompt design, system prompts, prompt optimization
- Self-hosting and local models: ollama, local llm, self-hosted, open source models, llama, on-prem models, vllm, local models
- Git and version control: git, github, gitlab, version control
- RAG pipelines: rag, retrieval augmented generation, retrieval-augmented generation, embeddings, vector search, semantic search, chunking, knowledge retrieval
- Agent orchestration and MCP: ai agents, agents, agentic, mcp, model context protocol, tool calling, function calling, multi-agent, orchestration, agent frameworks
- AI-assisted development tooling: copilot, github copilot, cursor, claude code, ai coding tools, ai-assisted development
- Cloud basics: aws, azure, gcp, google cloud, cloud, cloud services
- Docker: docker, containers, containerization, docker compose, containerisation
- Evaluation and testing of LLM output: llm evaluation, evals, evaluation, ragas, model evaluation, quality metrics, benchmarking, evaluation frameworks, llm testing
- ML fundamentals: machine learning, ml, scikit-learn, sklearn, supervised learning, ml models
- Vector databases by name: pinecone, weaviate, pgvector, chroma, chromadb, qdrant, milvus, vector database, faiss, vector store
- LangChain or LlamaIndex: langchain, llamaindex, llama index, langgraph, semantic kernel, haystack
- Model fine-tuning: fine-tuning, fine tuning, lora, training models, peft, model training
- MLOps: mlops, model deployment, mlflow, model monitoring, sagemaker, vertex ai, ml pipelines
