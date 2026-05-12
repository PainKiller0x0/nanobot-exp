use chrono::Utc;
use regex::Regex;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::markdown::parse_html_preserving_inline_markdown;

#[derive(Debug, Deserialize, Default)]
pub(crate) struct CleanMarkdownPayload {
    pub(crate) title: Option<String>,
    pub(crate) source: Option<String>,
    pub(crate) published_at: Option<String>,
    pub(crate) content: Option<String>,
    pub(crate) input_format: Option<String>,
    pub(crate) smart_merge: Option<bool>,
    pub(crate) merge_mode: Option<String>,
}

fn clean_control_text(input: &str) -> String {
    input
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .chars()
        .filter(|c| {
            !matches!(
                *c,
                '\u{0000}'..='\u{0008}'
                    | '\u{000B}'
                    | '\u{000C}'
                    | '\u{000E}'..='\u{001F}'
                    | '\u{007F}'
                    | '\u{200B}'
                    | '\u{200C}'
                    | '\u{200D}'
                    | '\u{FEFF}'
            )
        })
        .collect()
}

fn looks_like_html(input: &str) -> bool {
    let lower = input.to_lowercase();
    [
        "<p", "<br", "<div", "<section", "<article", "<span", "<h1", "<h2", "<strong", "<em",
        "<img",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
}

fn is_cleaner_noise_line(line: &str) -> bool {
    let t = line.trim();
    if t.is_empty() {
        return false;
    }
    let exact = [
        "文章原文",
        "原文",
        "原文链接",
        "Original",
        "Original:",
        "Open Link",
        "阅读原文",
        "继续滑动看下一个",
        "向上滑动看下一个",
        "喜欢此内容的人还喜欢",
    ];
    if exact.iter().any(|x| t.eq_ignore_ascii_case(x)) {
        return true;
    }
    [
        "微信扫一扫",
        "长按二维码",
        "识别二维码",
        "已关注",
        "分享到朋友圈",
        "赞和在看",
    ]
    .iter()
    .any(|needle| t.contains(needle))
}

fn is_markdown_structural_line(line: &str) -> bool {
    let t = line.trim_start();
    if t.is_empty() {
        return false;
    }
    if t.starts_with('#')
        || t.starts_with('>')
        || t.starts_with('|')
        || t.starts_with("```")
        || t.starts_with("---")
        || t.starts_with("![")
        || t.starts_with("- ")
        || t.starts_with("* ")
        || t.starts_with("+ ")
    {
        return true;
    }
    Regex::new(r"^\d+[.)、]\s+").unwrap().is_match(t)
}

fn ends_sentence(line: &str) -> bool {
    let t = line.trim_end();
    if t.is_empty() {
        return false;
    }
    t.ends_with('。')
        || t.ends_with('！')
        || t.ends_with('？')
        || t.ends_with('；')
        || t.ends_with(';')
        || t.ends_with('!')
        || t.ends_with('?')
        || t.ends_with('.')
        || t.ends_with('：')
        || t.ends_with(':')
        || t.ends_with('”')
        || t.ends_with('’')
        || t.ends_with('」')
        || t.ends_with('』')
        || t.ends_with('）')
        || t.ends_with(')')
        || t.ends_with('】')
}

fn starts_with_punctuation(line: &str) -> bool {
    line.trim_start()
        .chars()
        .next()
        .map(|c| "，,。.!！?？；;：:、）)]】」』”’".contains(c))
        .unwrap_or(false)
}

fn join_inline(left: &str, right: &str) -> String {
    let l = left.trim_end();
    let r = right.trim_start();
    let left_c = l.chars().last().unwrap_or(' ');
    let right_c = r.chars().next().unwrap_or(' ');
    let need_space = left_c.is_ascii_alphanumeric() && right_c.is_ascii_alphanumeric();
    if starts_with_punctuation(r) || !need_space {
        format!("{l}{r}")
    } else {
        format!("{l} {r}")
    }
}

fn visible_char_count(line: &str) -> usize {
    line.chars().filter(|c| !c.is_whitespace()).count()
}

fn ends_soft_connector(line: &str) -> bool {
    line.trim_end()
        .chars()
        .last()
        .map(|c| "，,、：:；;（(《“‘「『".contains(c))
        .unwrap_or(false)
}

fn ends_mid_clause(line: &str) -> bool {
    line.trim_end()
        .chars()
        .last()
        .map(|c| "，,、；;：:".contains(c))
        .unwrap_or(false)
}

fn should_merge_paid_lines(current: &str, next: &str) -> bool {
    let cur = current.trim();
    let nxt = next.trim();
    if cur.is_empty() || nxt.is_empty() {
        return false;
    }
    if starts_with_punctuation(nxt) || ends_soft_connector(cur) || ends_mid_clause(nxt) {
        return true;
    }
    if is_markdown_structural_line(cur) || is_markdown_structural_line(nxt) {
        return false;
    }

    // Only treat a long non-terminal line as a visual wrap. Short metadata-like
    // lines such as author/date/location should stay as separate paragraphs.
    visible_char_count(cur) >= 30 && !ends_sentence(cur)
}

fn normalize_paid_article_markdown(markdown: &str, smart_merge: bool) -> String {
    let cleaned = clean_control_text(markdown);
    let mut paragraphs: Vec<String> = Vec::new();
    let mut current = String::new();

    let flush = |current: &mut String, paragraphs: &mut Vec<String>| {
        let text = current.trim();
        if !text.is_empty() {
            paragraphs.push(text.to_string());
        }
        current.clear();
    };

    for raw in cleaned.lines() {
        let line = raw.trim();
        if line.is_empty() {
            flush(&mut current, &mut paragraphs);
            continue;
        }
        if is_cleaner_noise_line(line) {
            continue;
        }
        if !smart_merge || is_markdown_structural_line(line) {
            flush(&mut current, &mut paragraphs);
            paragraphs.push(line.to_string());
            continue;
        }
        if current.is_empty() {
            current = line.to_string();
        } else if should_merge_paid_lines(&current, line) {
            current = join_inline(&current, line);
        } else {
            flush(&mut current, &mut paragraphs);
            current = line.to_string();
        }
    }
    flush(&mut current, &mut paragraphs);

    let mut out = paragraphs.join("\n\n");
    let blank_re = Regex::new(r"\n{3,}").unwrap();
    out = blank_re.replace_all(&out, "\n\n").to_string();
    out.trim().to_string()
}

fn sentence_end_char(c: char) -> bool {
    matches!(c, '。' | '！' | '？' | '!' | '?')
}

fn insert_paid_article_break_hints(text: &str) -> String {
    let mut s = text.to_string();
    s = Regex::new(r"(\.{3,})")
        .unwrap()
        .replace_all(&s, "……")
        .to_string();
    s = Regex::new(r"以下进入正文\s*[:：]?")
        .unwrap()
        .replace_all(&s, "\n\n")
        .to_string();
    s = Regex::new(r"(第[一二三四五六七八九十百0-9]+个话题[，,：:])")
        .unwrap()
        .replace_all(&s, "\n\n$1")
        .to_string();

    for marker in [
        "好，我们",
        "那么",
        "反过来",
        "再比如",
        "所以",
        "于是",
        "你看，",
        "这就叫",
        "说到底",
        "我们总结下",
    ] {
        let pat = format!(r"([。！？!?]|……)({})", regex::escape(marker));
        s = Regex::new(&pat)
            .unwrap()
            .replace_all(&s, "$1\n\n$2")
            .to_string();
    }
    s
}

fn split_paid_article_sentences(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for c in text.chars() {
        current.push(c);
        let is_ellipsis_end = c == '\u{2026}' && current.ends_with("\u{2026}\u{2026}");
        if sentence_end_char(c) || is_ellipsis_end {
            let trimmed = current.trim();
            if !trimmed.is_empty() {
                out.push(trimmed.to_string());
            }
            current.clear();
        }
    }
    let tail = current.trim();
    if !tail.is_empty() {
        out.push(tail.to_string());
    }
    out
}

fn is_topic_heading_sentence(sentence: &str) -> bool {
    Regex::new(r"^第[一二三四五六七八九十百0-9]+个话题[，,：:]")
        .unwrap()
        .is_match(sentence.trim())
}

fn starts_discourse_block(sentence: &str) -> bool {
    let t = sentence.trim_start();
    [
        "好，我们",
        "那么",
        "反过来",
        "再比如",
        "所以",
        "于是",
        "你看，",
        "这就叫",
        "说到底",
        "我们总结下",
    ]
    .iter()
    .any(|prefix| t.starts_with(prefix))
        || is_topic_heading_sentence(t)
}

fn push_sentence_group(groups: &mut Vec<String>, current: &mut String) {
    let text = current.trim();
    if !text.is_empty() {
        groups.push(text.to_string());
    }
    current.clear();
}

fn is_short_answer_sentence(sentence: &str) -> bool {
    let t = sentence.trim();
    visible_char_count(t) <= 8
        && (t.starts_with("\u{662F}")
            || t.starts_with("\u{4E0D}\u{662F}")
            || t.starts_with("\u{4E0D}")
            || t.starts_with("\u{80FD}")
            || t.starts_with("\u{4E0D}\u{80FD}")
            || t.starts_with("\u{4F1A}")
            || t.starts_with("\u{4E0D}\u{4F1A}")
            || t.starts_with("\u{6CA1}")
            || t.starts_with("\u{6709}"))
}

fn starts_demonstrative_continuation(sentence: &str) -> bool {
    let t = sentence.trim_start();
    [
        "\u{8FD9}\u{4E2A}",
        "\u{8FD9}\u{79CD}",
        "\u{8FD9}\u{7C7B}",
        "\u{8FD9}\u{4E9B}",
        "\u{8FD9}\u{70B9}",
        "\u{8FD9}\u{53E5}",
        "\u{8FD9}\u{4EF6}\u{4E8B}",
        "\u{8FD9}\u{65F6}",
        "\u{8FD9}\u{5C31}",
        "\u{8FD9}\u{624D}",
        "\u{5C31}\u{50CF}",
        "\u{597D}\u{6BD4}",
        "\u{6BD4}\u{5982}",
        "\u{5B83}",
        "\u{4ED6}",
        "\u{5979}",
        "\u{4EBA}\u{5BB6}",
        "\u{524D}\u{8005}",
        "\u{540E}\u{8005}",
    ]
    .iter()
    .any(|prefix| t.starts_with(prefix))
}

fn starts_parallel_contrast_continuation(sentence: &str) -> bool {
    let t = sentence.trim_start();
    [
        "\u{4E0D}\u{5954}",
        "\u{4E0D}\u{4EE5}",
        "\u{4E0D}\u{9760}",
        "\u{4E0D}\u{53BB}",
    ]
    .iter()
    .any(|prefix| t.starts_with(prefix))
}

fn should_join_paid_sentences(current: &str, sentence: &str) -> bool {
    let cur = current.trim();
    let next = sentence.trim();
    if cur.is_empty() || next.is_empty() {
        return false;
    }
    if cur == "\u{2026}\u{2026}" || next == "\u{2026}\u{2026}" || starts_discourse_block(next) {
        return false;
    }

    let cur_len = visible_char_count(cur);
    let next_len = visible_char_count(next);

    // Keep explanatory follow-up sentences with their antecedent. This handles
    // copied paid articles where WeChat drops original paragraph breaks, e.g.
    // "...a new person. This new self..." should stay in one paragraph.
    if starts_demonstrative_continuation(next)
        && cur_len >= 20
        && next_len <= 80
        && cur_len + next_len <= 120
    {
        return true;
    }

    if starts_parallel_contrast_continuation(next)
        && cur_len <= 48
        && next_len <= 48
        && cur_len + next_len <= 100
    {
        return true;
    }

    if (cur.ends_with('\u{FF1F}') || cur.ends_with('?'))
        && next_len <= 8
        && is_short_answer_sentence(next)
    {
        return true;
    }

    // Keep tightly-coupled rhetorical Q/A in one paragraph, e.g. "but is he convinced? no.".
    // Other short rhythm lines are intentionally left standalone because the RSS samples
    // show Bishu often uses them as paragraph beats instead of inline clauses.
    if (cur.ends_with('\u{FF1F}') || cur.ends_with('?'))
        && (next.ends_with('\u{FF1F}') || next.ends_with('?'))
        && cur_len + next_len <= 80
    {
        return true;
    }
    false
}

fn group_paid_article_sentences(sentences: &[String]) -> Vec<String> {
    let mut groups = Vec::new();
    let mut current = String::new();

    // Bishu Xifeng's RSS articles are paragraph-dense, but not length-chopped:
    // recent samples are mostly sentence-sized paragraphs with many standalone
    // rhetorical beats. Split on real sentence/ellipsis boundaries, and only join
    // a tiny set of inseparable Q/A fragments.
    for sentence in sentences {
        if !current.is_empty() && !should_join_paid_sentences(&current, sentence) {
            push_sentence_group(&mut groups, &mut current);
        }
        if current.is_empty() {
            current = sentence.trim().to_string();
        } else {
            current = join_inline(&current, sentence);
        }
    }
    push_sentence_group(&mut groups, &mut current);
    groups
}

fn segment_paid_article_paragraph(paragraph: &str) -> Vec<String> {
    let text = paragraph.trim();
    if text.is_empty() {
        return Vec::new();
    }
    if is_markdown_structural_line(text) {
        return vec![text.to_string()];
    }

    let sentences = split_paid_article_sentences(text);
    if !sentences.is_empty() && is_topic_heading_sentence(&sentences[0]) {
        let mut heading = sentences[0].trim().to_string();
        let mut rest_start = 1;
        while rest_start < sentences.len()
            && visible_char_count(&heading) < 90
            && visible_char_count(&sentences[rest_start]) <= 32
            && (sentences[rest_start].trim_end().ends_with('？')
                || sentences[rest_start].trim_end().ends_with('?'))
        {
            heading = join_inline(&heading, &sentences[rest_start]);
            rest_start += 1;
        }
        let mut out = vec![format!("## {}", heading.trim())];
        out.extend(group_paid_article_sentences(&sentences[rest_start..]));
        return out;
    }

    if sentences.len() <= 1 {
        return vec![text.to_string()];
    }
    group_paid_article_sentences(&sentences)
}

fn auto_segment_paid_article_markdown(markdown: &str) -> String {
    let hinted = insert_paid_article_break_hints(markdown);
    let mut out = Vec::new();
    for paragraph in hinted.split("\n\n") {
        out.extend(segment_paid_article_paragraph(paragraph));
    }
    out.into_iter()
        .filter(|p| !p.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn remove_duplicate_title_prefix(markdown: &str, title: &str) -> String {
    let title = title.trim();
    if title.is_empty() {
        return markdown.trim().to_string();
    }
    let mut lines: Vec<&str> = markdown.lines().collect();
    while let Some(first) = lines.first() {
        let clean = first
            .trim()
            .trim_start_matches('#')
            .trim()
            .trim_matches('【')
            .trim_matches('】')
            .trim();
        if clean == title || clean.is_empty() {
            lines.remove(0);
            continue;
        }
        break;
    }
    lines.join("\n").trim().to_string()
}

fn sanitize_markdown_filename(title: &str) -> String {
    let base = if title.trim().is_empty() {
        format!("wechat-paid-article-{}", Utc::now().format("%Y%m%d-%H%M"))
    } else {
        title.trim().to_string()
    };
    let mut s = base
        .chars()
        .map(|c| match c {
            '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '-',
            _ => c,
        })
        .collect::<String>();
    s = Regex::new(r"\s+").unwrap().replace_all(&s, " ").to_string();
    s.truncate(80);
    if !s.ends_with(".md") {
        s.push_str(".md");
    }
    s
}

pub(crate) struct PreparedPaidArticle {
    pub(crate) body: String,
    pub(crate) as_html: bool,
    pub(crate) smart_merge: bool,
    pub(crate) effective_merge_mode: String,
}

pub(crate) fn prepare_paid_article_body(
    payload: &CleanMarkdownPayload,
    apply_auto_segment: bool,
) -> PreparedPaidArticle {
    let title = payload.title.as_deref().unwrap_or("").trim();
    let raw = payload.content.as_deref().unwrap_or("");
    let input_format = payload
        .input_format
        .as_deref()
        .unwrap_or("auto")
        .trim()
        .to_ascii_lowercase();
    let merge_mode_raw = payload.merge_mode.as_deref().unwrap_or("").trim();
    let effective_merge_mode = if merge_mode_raw.is_empty() {
        "auto".to_string()
    } else {
        merge_mode_raw.to_ascii_lowercase()
    };
    let smart_merge = if merge_mode_raw.is_empty() {
        payload.smart_merge.unwrap_or(false)
    } else {
        matches!(effective_merge_mode.as_str(), "smart" | "compact" | "merge")
    };
    let auto_segment = apply_auto_segment
        && matches!(
            effective_merge_mode.as_str(),
            "auto" | "segment" | "paragraph"
        );
    let as_html = input_format == "html" || (input_format == "auto" && looks_like_html(raw));

    let markdown_raw = if as_html {
        parse_html_preserving_inline_markdown(raw)
    } else {
        raw.to_string()
    };
    let mut body = normalize_paid_article_markdown(&markdown_raw, smart_merge);
    if auto_segment {
        body = auto_segment_paid_article_markdown(&body);
    }
    let body = remove_duplicate_title_prefix(&body, title);
    PreparedPaidArticle {
        body,
        as_html,
        smart_merge,
        effective_merge_mode,
    }
}

pub(crate) fn assemble_paid_article_markdown(payload: &CleanMarkdownPayload, body: &str) -> String {
    let title = payload.title.as_deref().unwrap_or("").trim();
    let source = payload.source.as_deref().unwrap_or("").trim();
    let published_at = payload.published_at.as_deref().unwrap_or("").trim();
    let mut parts: Vec<String> = Vec::new();
    if !title.is_empty() {
        parts.push(format!("# {title}"));
    }
    if !source.is_empty() {
        parts.push(format!("> \u{6765}\u{6E90}\u{FF1A}{source}"));
    }
    if !published_at.is_empty() {
        parts.push(format!(
            "*\u{53D1}\u{5E03}\u{65F6}\u{95F4}\u{FF1A}{published_at}*"
        ));
    }
    if !body.trim().is_empty() {
        parts.push(body.trim().to_string());
    }
    parts.join("\n\n").trim().to_string()
}

fn markdown_stats(markdown: &str) -> (usize, usize) {
    (markdown.lines().count(), markdown.chars().count())
}

pub(crate) fn build_paid_article_cleaner_response(
    payload: &CleanMarkdownPayload,
    prepared: &PreparedPaidArticle,
    markdown: String,
    cleaner_engine: &str,
    llm_cleaner_status: &str,
) -> Value {
    let title = payload.title.as_deref().unwrap_or("").trim();
    let (line_count, char_count) = markdown_stats(&markdown);
    json!({
        "ok": true,
        "markdown": markdown,
        "filename": sanitize_markdown_filename(title),
        "input_format": if prepared.as_html { "html" } else { "text" },
        "smart_merge": prepared.smart_merge,
        "merge_mode": prepared.effective_merge_mode,
        "line_count": line_count,
        "char_count": char_count,
        "cleaner_engine": cleaner_engine,
        "llm_cleaner_status": llm_cleaner_status,
    })
}

pub(crate) fn clean_paid_article_payload(payload: &CleanMarkdownPayload) -> Value {
    let prepared = prepare_paid_article_body(payload, true);
    let markdown = assemble_paid_article_markdown(payload, &prepared.body);
    build_paid_article_cleaner_response(payload, &prepared, markdown, "local_rules", "not_used")
}

fn whitespace_compact_for_compare(s: &str) -> String {
    s.chars().filter(|c| !c.is_whitespace()).collect()
}

pub(crate) fn markdown_integrity_ok(before: &str, after: &str) -> bool {
    whitespace_compact_for_compare(before) == whitespace_compact_for_compare(after)
}

pub(crate) fn set_cleaner_llm_result(result: &mut Value, status: &str, message: Option<String>) {
    result["llm_cleaner"] = json!("longcat-flash-lite");
    result["llm_cleaner_status"] = json!(status);
    if let Some(v) = message {
        result["llm_cleaner_message"] = json!(v.chars().take(240).collect::<String>());
    }
}
