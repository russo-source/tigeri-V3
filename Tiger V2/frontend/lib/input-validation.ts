const CONTROL_CHARS_RE = /[\u0000-\u001F\u007F]/g;
const UNSAFE_TEXT_CHARS_RE = /[<>`]/g;
const MULTI_SPACE_RE = /\s+/g;
const EMAIL_FORMAT_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const clampLength = (value: string, maxLength: number) => {
	if (maxLength <= 0) {
		return "";
	}

	return value.length > maxLength ? value.slice(0, maxLength) : value;
};

const sanitizeSingleLine = (value: string) => {
	return value.replace(CONTROL_CHARS_RE, "").replace(UNSAFE_TEXT_CHARS_RE, "");
};

export const sanitizeEmailInput = (value: string, maxLength = 254) => {
	const normalized = sanitizeSingleLine(value).replace(MULTI_SPACE_RE, "").trim();
	return clampLength(normalized, maxLength);
};

export const isValidEmailFormat = (value: string) => {
	const normalized = sanitizeEmailInput(value);
	if (!normalized || normalized.length > 254 || !EMAIL_FORMAT_RE.test(normalized)) {
		return false;
	}

	const [localPart, domainPart] = normalized.split("@");
	if (!localPart || !domainPart) {
		return false;
	}

	if (localPart.length > 64 || domainPart.length > 255) {
		return false;
	}

	return true;
};

export const sanitizePhoneInput = (value: string, maxLength = 20) => {
	const digitsOnly = value.replace(/\D/g, "");
	return clampLength(digitsOnly, maxLength);
};

export const sanitizePersonName = (value: string, maxLength = 80) => {
	const normalized = sanitizeSingleLine(value)
		.replace(MULTI_SPACE_RE, " ")
		.trimStart();
	return clampLength(normalized, maxLength);
};

export const sanitizeBusinessText = (value: string, maxLength = 120) => {
	const normalized = sanitizeSingleLine(value)
		.replace(MULTI_SPACE_RE, " ")
		.trimStart();
	return clampLength(normalized, maxLength);
};

export const sanitizeSearchText = (value: string, maxLength = 120) => {
	const normalized = sanitizeSingleLine(value)
		.replace(MULTI_SPACE_RE, " ")
		.trimStart();
	return clampLength(normalized, maxLength);
};

export const sanitizeSecretLike = (value: string, maxLength = 128) => {
	const normalized = value.replace(CONTROL_CHARS_RE, "");
	return clampLength(normalized, maxLength);
};

export const sanitizeMultilineText = (value: string, maxLength = 1200) => {
	const normalized = value
		.replace(/\r\n?/g, "\n")
		.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
		.replace(UNSAFE_TEXT_CHARS_RE, "");

	return clampLength(normalized, maxLength);
};
