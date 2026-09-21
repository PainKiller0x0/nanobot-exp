pub const FREE_LLM_BASE_URL: &str = "https://api.longcat.chat/openai/v1";
pub const FREE_LLM_MODEL: &str = "LongCat-Flash-Lite";
pub const FREE_EMBEDDING_ENDPOINT: &str = "https://api.siliconflow.cn/v1/embeddings";
pub const FREE_EMBEDDING_MODEL: &str = "BAAI/bge-m3";

pub fn env_bool(name: &str, default: bool) -> bool {
    match std::env::var(name) {
        Ok(v) => matches!(
            v.trim().to_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
        Err(_) => default,
    }
}

pub fn is_free_llm(base_url: &str, model: &str) -> bool {
    base_url.to_lowercase().contains("longcat")
        && model.to_lowercase().contains("longcat-flash-lite")
}

pub fn is_free_embedding(endpoint: &str, model: &str) -> bool {
    endpoint.to_lowercase().contains("siliconflow") && model.to_lowercase().contains("bge")
}

pub fn llm_enabled(api_key: &str, base_url: &str, model: &str) -> bool {
    env_bool("REFLEXIO_LLM_FACTS_ENABLED", true)
        && !api_key.trim().is_empty()
        && (env_bool("REFLEXIO_ALLOW_PAID_LLM", false) || is_free_llm(base_url, model))
}

pub fn embedding_enabled(api_key: &str, endpoint: &str, model: &str) -> bool {
    env_bool("REFLEXIO_EMBEDDING_ENABLED", true)
        && !api_key.trim().is_empty()
        && (env_bool("REFLEXIO_ALLOW_PAID_EMBEDDING", false) || is_free_embedding(endpoint, model))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identifies_free_model_backends() {
        assert!(is_free_llm(FREE_LLM_BASE_URL, FREE_LLM_MODEL));
        assert!(!is_free_llm("https://api.deepseek.com", "deepseek-v4-pro"));
        assert!(is_free_embedding(
            FREE_EMBEDDING_ENDPOINT,
            FREE_EMBEDDING_MODEL
        ));
        assert!(!is_free_embedding(
            "https://paid.example.com",
            "paid-embedding"
        ));
    }

    #[test]
    fn default_policy_disables_paid_backends() {
        assert!(llm_enabled("key", FREE_LLM_BASE_URL, FREE_LLM_MODEL));
        assert!(!llm_enabled(
            "key",
            "https://api.deepseek.com",
            "deepseek-v4-pro"
        ));
        assert!(!llm_enabled("", FREE_LLM_BASE_URL, FREE_LLM_MODEL));
        assert!(embedding_enabled(
            "key",
            FREE_EMBEDDING_ENDPOINT,
            FREE_EMBEDDING_MODEL
        ));
        assert!(!embedding_enabled(
            "key",
            "https://paid.example.com",
            "paid-embedding"
        ));
    }
}
