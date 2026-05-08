function getStatusPill(status: string) {
    if (status === "approved") return "tag-approved";
    if (status === "pending") return "tag-pending";
    return "tag-rejected";
}

function formatDate(raw: string | null | undefined) {
    if (!raw) return "-";

    const date = new Date(raw);
    if (isNaN(date.getTime())) return "-";

    return date.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "UTC"
    });
}

function formatTime(raw: string | null | undefined) {
    if (!raw) return "";

    const date = new Date(raw);
    if (isNaN(date.getTime())) return "";

    return date.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC"
    });
}

function formatDateAndTime(raw: string | null | undefined) {
    if (!raw) return "-";

    const date = new Date(raw);
    if (isNaN(date.getTime())) return "-";

    return (
        date.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            timeZone: "UTC"
        }) +
        " " +
        date.toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            timeZone: "UTC"
        })
    );
}

function truncateText(value: string, maxChars = 12) {
    const trimmed = value.trim();

    if (!trimmed) return value;

    if (trimmed.length > maxChars) {
        return `${trimmed.slice(0, maxChars)}...`;
    }

    return value;
}

export { formatDate, formatTime, formatDateAndTime, getStatusPill, truncateText }