const lastVerificationCodeByEmail = new Map();
export function normalizeMailbox(value) {
    const input = String(value ?? "").trim().toLowerCase();
    const angleMatch = input.match(/<([^>]+)>/);
    return (angleMatch?.[1] ?? input).trim();
}
function normalizeTextForCodeMatching(text) {
    return String(text ?? "")
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
        .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&#(\d+);/g, (_, codePoint) => String.fromCharCode(Number(codePoint)))
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/g, "'")
        .replace(/\s+/g, " ")
        .trim();
}
function normalizeSixDigitCode(value) {
    const digitsOnly = String(value ?? "").replace(/\D/g, "");
    return digitsOnly.length === 6 ? digitsOnly : "";
}
function extractVerificationCode(text) {
    const raw = normalizeTextForCodeMatching(text);
    if (!raw) {
        return "";
    }
    const contextPatterns = [
        /\b((?:\d[\s-]*){6})\b(?=.{0,80}\b(?:is your|your|OpenAI|ChatGPT|verification|security|login|sign[-\s]?in|code|验证码)\b)/i,
        /\b(?:OpenAI|ChatGPT|verification|security|login|sign[-\s]?in|code|验证码)\b.{0,120}?\b((?:\d[\s-]*){6})\b/i,
        /\b((?:\d[\s-]*){6})\b.{0,80}?\b(?:OpenAI|ChatGPT|verification|security|login|sign[-\s]?in|code|验证码)\b/i,
    ];
    for (const pattern of contextPatterns) {
        const matched = raw.match(pattern);
        const code = normalizeSixDigitCode(matched?.[1]);
        if (code) {
            return code;
        }
    }
    const directMatch = raw.match(/\b(\d{6})\b/);
    if (directMatch?.[1]) {
        return directMatch[1];
    }
    return normalizeSixDigitCode(raw.match(/(?:^|[^\d])((?:\d[\s-]*){6})(?:[^\d]|$)/)?.[1]);
}
function normalizeRecipientList(recipient) {
    if (Array.isArray(recipient)) {
        return recipient
            .map((item) => normalizeMailbox(item))
            .filter(Boolean);
    }
    const normalized = normalizeMailbox(recipient ?? "");
    return normalized ? [normalized] : [];
}
function collectCandidateTexts(mail) {
    const texts = [mail.subject ?? "", mail.content ?? "", ...(mail.extraTexts ?? [])];
    return texts
        .map((item) => String(item ?? "").trim())
        .filter(Boolean);
}
export function findLatestVerificationMail(mails, options = {}) {
    const targetEmail = normalizeMailbox(options.targetEmail ?? "");
    const previousCode = targetEmail ? lastVerificationCodeByEmail.get(targetEmail) ?? "" : "";
    const sorted = [...mails].sort((left, right) => Number(right.timestamp ?? 0) - Number(left.timestamp ?? 0));
    for (const mail of sorted) {
        if (targetEmail) {
            const recipients = normalizeRecipientList(mail.recipient);
            if (recipients.length > 0 && !recipients.includes(targetEmail)) {
                continue;
            }
        }
        if (options.candidateMatcher && !options.candidateMatcher(mail)) {
            continue;
        }
        const verificationCode = collectCandidateTexts(mail)
            .map((text) => extractVerificationCode(text))
            .find(Boolean) ?? "";
        if (!verificationCode) {
            continue;
        }
        if (previousCode && verificationCode === previousCode) {
            continue;
        }
        const matchedMail = {
            ...mail,
            verificationCode,
        };
        if (targetEmail && options.rememberLastCode !== false) {
            lastVerificationCodeByEmail.set(targetEmail, verificationCode);
        }
        return matchedMail;
    }
    return null;
}
