// Read only the widget's public checked/error indicators. Never read response tokens,
// click a checkbox, solve a challenge, call execute(), or change verification state.
export function readRecaptchaIndicator() {
  const anchor = document.getElementById("recaptcha-anchor");
  const visible = (el) =>
    !!el &&
    el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== "hidden";
  const error = [
    ...document.querySelectorAll(
      ".rc-anchor-error-msg,.rc-anchor-error-message",
    ),
  ].some((el) => visible(el) && !!el.textContent.trim());
  return {
    checked: visible(anchor) && anchor.getAttribute("aria-checked") === "true",
    error,
  };
}
export const trustedRecaptchaFrame = (url) =>
  /^https:\/\/(?:www\.)?(?:google\.com|recaptcha\.net)\/recaptcha\/(?:api2|enterprise)\//i.test(
    url,
  );
export const recaptchaAnchor = (url) =>
  trustedRecaptchaFrame(url) && /\/anchor(?:\?|$)/.test(url);
