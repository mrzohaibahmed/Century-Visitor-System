/** Select the intended portal when badge and belongings copies are mounted together. */
let clearAfterPrint: (() => void) | null = null;

export function printOnly(target: "badge" | "belongings", source?: "completion") {
  clearAfterPrint?.();
  document.body.dataset.printTarget = target;
  if (source) document.body.dataset.printSource = source;
  else delete document.body.dataset.printSource;
  const clear = () => {
    window.removeEventListener("afterprint", clear);
    if (document.body.dataset.printTarget === target) {
      delete document.body.dataset.printTarget;
      delete document.body.dataset.printSource;
    }
    if (clearAfterPrint === clear) clearAfterPrint = null;
  };
  clearAfterPrint = clear;
  window.addEventListener("afterprint", clear);
  window.print();
}
