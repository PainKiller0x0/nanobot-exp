use regex::Regex;
use serde_json::Value;

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("valid regex")
}

fn strip_control_chars(text: &str) -> String {
    re(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u{200b}\u{200c}\u{200d}\u{feff}]")
        .replace_all(text, "")
        .to_string()
}

fn collapse_blank_lines(text: &str) -> String {
    re(r"\n{3,}").replace_all(text, "\n\n").trim().to_string()
}

fn markdown_signal_text(markdown: &str) -> String {
    let mut text = strip_control_chars(markdown);
    for pattern in [
        r"(?i)<img\b[^>]*>",
        r"!\[[^\]]*]\([^)]+\)",
        r"https?://[^\s)]+",
        r"</?[^>]+>",
    ] {
        text = re(pattern).replace_all(&text, " ").to_string();
    }
    text = re(r"\[([^\]]+)]\(https?://[^)]+\)")
        .replace_all(&text, " $1 ")
        .to_string();
    re(r"\s+").replace_all(&text, " ").trim().to_string()
}

fn wechat_paid_teaser_tail(text: &str) -> Option<String> {
    let marker = re(r"以下进入正文\s*[:：]?");
    let m = marker.find(text)?;
    let mut tail = text[m.end()..].to_string();
    tail = re(r"(?i)(文章原文|原文链接|原文地址|原文|Original:?|Open Link)")
        .replace_all(&tail, " ")
        .to_string();
    tail = re(r"[\s:：,，.。;；!！?？·\-—_|\[\]【】（）()]+")
        .replace_all(&tail, "")
        .trim()
        .to_string();
    Some(tail)
}

fn is_wechat_paid_teaser(markdown: &str) -> bool {
    let text = markdown_signal_text(markdown);
    if text.is_empty() {
        return false;
    }
    let Some(tail) = wechat_paid_teaser_tail(&text) else {
        return false;
    };
    if tail.len() > 80 {
        return false;
    }
    let markers = [
        text.contains("以下进入正文"),
        text.contains("文中多处有链接"),
        text.contains("画中画"),
        text.contains("文中文"),
        re(r"全文.{0,20}(字|文字).{0,20}共分").is_match(&text),
        re(r"(本文下面|每一条留言).{0,20}我都会看到").is_match(&text),
    ];
    text.chars().count() <= 1800 && markers.iter().filter(|ok| **ok).count() >= 3
}

fn strip_markdown_images(markdown: &str) -> String {
    let text = re(r"(?i)<img\b[^>]*>")
        .replace_all(markdown, "")
        .to_string();
    re(r"!\[[^\]]*]\([^)]+\)")
        .replace_all(&text, "")
        .to_string()
}

fn remove_naked_urls_preserving_markdown_links(markdown: &str) -> String {
    let link_re = re(r"\[[^\]]+]\(https?://[^)]+\)");
    let mut links = Vec::<String>::new();
    let mut text = link_re
        .replace_all(markdown, |caps: &regex::Captures<'_>| {
            let idx = links.len();
            links.push(caps.get(0).map(|m| m.as_str()).unwrap_or("").to_string());
            format!("__NBMDLINK_{idx}__")
        })
        .to_string();
    text = re(r"https?://[^\s)]+").replace_all(&text, "").to_string();
    for (idx, original) in links.into_iter().enumerate() {
        text = text.replace(&format!("__NBMDLINK_{idx}__"), &original);
    }
    text
}

fn strip_html_tags(markdown: &str) -> String {
    re(r"</?[^>]+>").replace_all(markdown, "").to_string()
}

fn strip_source_link_lines(markdown: &str) -> String {
    let source_re = re(r"(?i)^(文章原文|原文|原文链接|原文地址)\s*(\(.+\))?$");
    let skip_values = [
        "文章原文",
        "原文",
        "原文链接",
        "Original",
        "Original:",
        "Open Link",
        "Original: Open Link",
    ];
    markdown
        .lines()
        .filter(|line| {
            let text = line.trim();
            !source_re.is_match(text) && !skip_values.contains(&text)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn article_meta_lines(source: &str, published: &str) -> Vec<String> {
    let mut lines = Vec::new();
    if !source.trim().is_empty() {
        lines.push(format!("· 来源 / Source: {}", source.trim()));
    }
    if !published.trim().is_empty() {
        lines.push(format!("· 发布时间 / Published: {}", published.trim()));
    }
    lines
}

fn strip_duplicate_title(markdown: &str, title: &str) -> String {
    if title.trim().is_empty() {
        return markdown.trim().to_string();
    }
    let escaped = regex::escape(title.trim());
    re(&format!(r"(?s)^\s*[\[【]?\s*{escaped}\s*[\]】]?\s*\n+"))
        .replace(markdown, "")
        .trim()
        .to_string()
}

fn clean_article_markdown(markdown: &str, title: &str) -> String {
    let mut text = strip_control_chars(markdown);
    text = strip_markdown_images(&text);
    text = remove_naked_urls_preserving_markdown_links(&text);
    text = strip_html_tags(&text);
    text = strip_source_link_lines(&text);
    text = collapse_blank_lines(&text);
    strip_duplicate_title(&text, title)
}

fn format_paid_teaser_notice(article: &Value) -> String {
    let title = article
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let title = if title.is_empty() {
        "未命名文章"
    } else {
        title
    };
    let link = article
        .get("link")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let source = article
        .get("subscription_name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let published = article
        .get("published_at_local")
        .or_else(|| article.get("published_at"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let mut parts = vec![title.to_string()];
    let meta = article_meta_lines(source, published).join("\n");
    if !meta.is_empty() {
        parts.push(meta);
    }
    parts.push("这篇看起来是付费文章导流 / 试读片段，RSS 没有抓到完整正文。\n\n我不转发试读原文，避免把导流内容当成完整文章。\n\n如果你想读全文，可以打开原文购买 / 阅读。".to_string());
    if !link.is_empty() {
        parts.push(format!("---\n\n[文章原文]({link})"));
    }
    parts.join("\n\n").trim().to_string()
}

pub(crate) fn format_article_push_body(article: &Value) -> String {
    let raw_markdown = article
        .get("article_markdown")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if is_wechat_paid_teaser(raw_markdown) {
        return format_paid_teaser_notice(article);
    }
    let title = article
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let link = article
        .get("link")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let source = article
        .get("subscription_name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let published = article
        .get("published_at_local")
        .or_else(|| article.get("published_at"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let head = if title.is_empty() {
        "未命名文章"
    } else {
        title
    };
    let markdown = clean_article_markdown(raw_markdown, title);
    let meta = article_meta_lines(source, published).join("\n");
    let mut parts = vec![head.to_string()];
    if !meta.trim().is_empty() {
        parts.push(meta);
    }
    if !markdown.trim().is_empty() {
        parts.push(markdown);
    }
    let mut body = parts.join("\n\n").trim().to_string();
    body =
        re(r"(?is)\n*(?:---\s*\n+)?\[(?:文章原文|原文|原文链接|Original)\]\(https?://[^)]+\)\s*$")
            .replace(&body, "")
            .trim()
            .to_string();
    if !link.is_empty() {
        body = format!("{body}\n\n---\n\n[文章原文]({link})");
    }
    body.trim().to_string()
}
