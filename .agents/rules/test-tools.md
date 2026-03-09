---
trigger: always_on
---

For testing use the pytest-django package documented here: https://pytest-django.readthedocs.io/en/latest/
When creating fixtures that involve django ORM models use the model-bakery package documented here: https://github.com/model-bakers/model_bakery
When testing the Django admin use `curl` command instead of the browser agent.
When testing involves sending to LLMs use the "openrouter" provider and model name "liquid/lfm-2.5-1.2b-instruct:free".
Do not use ollama in tests.