"""Curated research prompts for the live eval suite.

A small, diverse set that exercises the pipeline across domains and question
shapes (effects, regulation, causes, comparison, consensus). Deliberately short:
a live run hits the real provider and Tavily, so each prompt costs quota. Grow it
as the free-tier budget allows.
"""

EVAL_PROMPTS: list[str] = [
    "What are the main health effects of intermittent fasting on adults?",
    "How does the EU AI Act classify and regulate high-risk AI systems?",
    "What were the main causes of the 2023 Silicon Valley Bank collapse?",
    "How do solid-state and lithium-ion EV batteries compare?",
    "How do microplastics affect human health, per current research?",
]
