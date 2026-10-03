// Source links go only to the sources the index holds: Lime Green's site and its
// documents, and GOV.UK guidance (assets.publishing.service.gov.uk included).
const ALLOWED_HOSTS = ["lime-green.co.uk", "gov.uk"];

/** The link to show for a source address, or null when it is not on an allowed
 * host over HTTP(S), in which case the title is shown as plain text. */
export function safeLink(address: string): string | null {
  let url: URL;
  try {
    url = new URL(address);
  } catch {
    return null;
  }
  const web = url.protocol === "https:" || url.protocol === "http:";
  const allowed = ALLOWED_HOSTS.some(
    (host) => url.hostname === host || url.hostname.endsWith(`.${host}`),
  );
  return web && allowed ? url.href : null;
}
