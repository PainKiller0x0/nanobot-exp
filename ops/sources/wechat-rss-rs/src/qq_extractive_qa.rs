use regex::Regex;
use serde_json::{json, Value};
use std::collections::HashSet;

fn extract_question_tokens(question: &str) -> Vec<String> {
    let token_re = Regex::new(r"[\p{Han}]{2,}|[A-Za-z0-9_]{3,}").expect("valid token regex");
    let stop: HashSet<&'static str> = [
        "weixin",
        "wechat",
        "article",
        "latest",
        "question",
        "what",
        "which",
        "about",
        "tell",
        "please",
        "content",
        "this",
        "that",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
        "say",
        "says",
        "mention",
        "mentioned",
        "have",
        "has",
        "had",
        "there",
        "their",
        "from",
        "into",
        "with",
        "without",
        "http",
        "https",
        "com",
        "scene",
        "biz",
        "mid",
        "idx",
        "sn",
    ]
    .into_iter()
    .collect();
    let mut seen = HashSet::<String>::new();
    let mut out = Vec::<String>::new();
    for m in token_re.find_iter(question) {
        let token = m.as_str().to_string();
        let low = token.to_ascii_lowercase();
        if stop.contains(low.as_str()) || seen.contains(&low) {
            continue;
        }
        seen.insert(low);
        out.push(token);
        if out.len() >= 12 {
            break;
        }
    }
    out
}

pub(crate) fn extractive_answer(markdown: &str, question: &str, max_lines: usize) -> Value {
    let meta_re = Regex::new(r"(?i)^-\s*(Account|Biz|Published|Inserted|Original)\b")
        .expect("valid meta regex");
    let mut lines: Vec<String> = markdown
        .lines()
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .collect();
    if lines.first().is_some_and(|line| line.starts_with("# ")) {
        lines.remove(0);
    }
    lines.retain(|line| {
        !meta_re.is_match(line)
            && !line.contains("/ Account:")
            && !line.contains("/ Published:")
            && !line.contains("/ Inserted:")
            && !line.contains("/ Original:")
            && !line.starts_with("- Biz:")
    });
    if lines.is_empty() {
        return json!({"status":"not_found","answer":"NOT_FOUND_IN_ARTICLE","evidence":[],"tokens":[]});
    }
    let tokens = extract_question_tokens(question);
    if tokens.is_empty() {
        let evidence: Vec<String> = lines.into_iter().take(3).collect();
        let status = if evidence.is_empty() {
            "not_found"
        } else {
            "ok"
        };
        return json!({"status":status,"answer": if evidence.is_empty() { "NOT_FOUND_IN_ARTICLE".to_string() } else { evidence.join("\n") }, "evidence": evidence, "tokens":[]});
    }
    let mut scored = Vec::<(i32, usize, String)>::new();
    for line in lines {
        let low = line.to_lowercase();
        let mut score = 0_i32;
        for token in &tokens {
            if low.contains(&token.to_lowercase()) {
                score += 2;
            }
        }
        if score > 0 && line.contains("](") {
            score += 1;
        }
        if score > 0 {
            scored.push((score, line.chars().count(), line));
        }
    }
    scored.sort_by(|a, b| (b.0, b.1).cmp(&(a.0, a.1)));
    let mut evidence = Vec::<String>::new();
    for (_, _, line) in scored {
        if evidence.iter().any(|x| x == &line) {
            continue;
        }
        evidence.push(line);
        if evidence.len() >= max_lines {
            break;
        }
    }
    if evidence.is_empty() {
        json!({"status":"not_found","answer":"NOT_FOUND_IN_ARTICLE","evidence":[],"tokens":tokens})
    } else {
        json!({"status":"ok","answer":evidence.join("\n"),"evidence":evidence,"tokens":tokens})
    }
}
