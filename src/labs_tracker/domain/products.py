"""Product display defaults and legacy normalization."""

REPO_PRODUCT_DEFAULTS = {
    "MicrosoftLearning/mslearn-ai-agents": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-fundamentals": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-language": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-studio": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-vision": ["Foundry"],
    "MicrosoftLearning/mslearn-devops": ["Azure DevOps", "GitHub", "GitHub Actions", "GitHub Copilot"],
    "MicrosoftLearning/mslearn-genaiops": ["Foundry", "Azure Machine Learning Studio"],
    "MicrosoftLearning/mslearn-mlops": ["Azure Machine Learning Studio"],
    "MicrosoftLearning/mslearn-azure-ai": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-information-extraction": ["Foundry"],
    "MicrosoftLearning/dp-300-database-administrator": ["Azure SQL"],
    "MicrosoftLearning/PL-300-Microsoft-Power-BI-Data-Analyst": ["Power BI", "Microsoft Fabric"],
    "MicrosoftLearning/mslearn-sql-developer": ["Azure SQL"],
}


LEGACY_PRODUCT_ALIASES = {
    "Azure AI services": "Foundry",
    "Azure AI Language": "Foundry",
    "Azure AI Vision": "Foundry",
    "Azure AI Document Intelligence": "Foundry",
    "Azure Machine Learning": "Azure Machine Learning Studio",
    "PowerBI": "Power BI",
}


def repo_products(repo_id: str | None, products: list[str] | None) -> list[str]:
    values = products or REPO_PRODUCT_DEFAULTS.get(repo_id or "", [])
    normalized = []
    for product in values:
        normalized_product = LEGACY_PRODUCT_ALIASES.get(product, product)
        if normalized_product not in normalized:
            normalized.append(normalized_product)
    return normalized

