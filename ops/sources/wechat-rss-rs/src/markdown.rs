use html2md::parse_html;
use regex::Regex;

const MD_BOLD_OPEN_TOKEN: &str = "NBMDINLINEBOLDOPEN";
const MD_BOLD_CLOSE_TOKEN: &str = "NBMDINLINEBOLDCLOSE";
const MD_EM_OPEN_TOKEN: &str = "NBMDINLINEEMOPEN";
const MD_EM_CLOSE_TOKEN: &str = "NBMDINLINEEMCLOSE";

fn wrap_html_tag_with_markdown_tokens(
    html: &str,
    pattern: &str,
    open_token: &str,
    close_token: &str,
) -> String {
    let Ok(re) = Regex::new(pattern) else {
        return html.to_string();
    };
    re.replace_all(html, |caps: &regex::Captures| {
        let inner = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        if inner.trim().is_empty() {
            inner.to_string()
        } else {
            format!("{open_token}{inner}{close_token}")
        }
    })
    .to_string()
}

fn restore_inline_markdown_tokens(markdown: String) -> String {
    markdown
        .replace(MD_BOLD_OPEN_TOKEN, "**")
        .replace(MD_BOLD_CLOSE_TOKEN, "**")
        .replace(MD_EM_OPEN_TOKEN, "*")
        .replace(MD_EM_CLOSE_TOKEN, "*")
}

pub(crate) fn parse_html_preserving_inline_markdown(html: &str) -> String {
    let mut s = html.to_string();
    for pattern in [
        r"(?is)<strong\b[^>]*>(.*?)</strong>",
        r"(?is)<b\b[^>]*>(.*?)</b>",
    ] {
        s = wrap_html_tag_with_markdown_tokens(
            &s,
            pattern,
            MD_BOLD_OPEN_TOKEN,
            MD_BOLD_CLOSE_TOKEN,
        );
    }
    for pattern in [r"(?is)<em\b[^>]*>(.*?)</em>", r"(?is)<i\b[^>]*>(.*?)</i>"] {
        s = wrap_html_tag_with_markdown_tokens(&s, pattern, MD_EM_OPEN_TOKEN, MD_EM_CLOSE_TOKEN);
    }
    restore_inline_markdown_tokens(parse_html(&s))
}
