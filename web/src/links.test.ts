import { safeLink } from "./links";

test("links to Lime Green and GOV.UK pages are kept", () => {
  for (const address of [
    "https://www.lime-green.co.uk/products/duro#:~:text=Duro",
    "https://lime-green.co.uk/Documents/duro.pdf#page=2",
    "https://assets.publishing.service.gov.uk/media/guidance.pdf",
    "http://www.gov.uk/guidance/internal-wall-insulation",
  ]) {
    expect(safeLink(address)).toBe(new URL(address).href);
  }
});

test("other hosts, look-alikes, scripts and malformed addresses are not links", () => {
  for (const address of [
    "https://example.com/duro",
    "https://evil-lime-green.co.uk/duro",
    "https://lime-green.co.uk.example.com/duro",
    "javascript:alert(1)",
    "ftp://lime-green.co.uk/file",
    "not a url",
  ]) {
    expect(safeLink(address)).toBeNull();
  }
});
