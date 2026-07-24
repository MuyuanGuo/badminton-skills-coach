document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target || !navigator.clipboard) return;
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(target.innerText);
      button.textContent = document.documentElement.lang === "en" ? "Copied" : "已复制";
      window.setTimeout(() => { button.textContent = original; }, 1600);
    } catch {
      button.textContent = document.documentElement.lang === "en" ? "Select text" : "请手动选择";
    }
  });
});

document.querySelectorAll("[data-evidence-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    const tablist = tab.closest("[role='tablist']");
    if (!tablist) return;
    tablist.querySelectorAll("[data-evidence-tab]").forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      const panel = document.getElementById(candidate.dataset.evidenceTab);
      if (panel) panel.hidden = !selected;
    });
  });

  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const tabs = [...tab.closest("[role='tablist']").querySelectorAll("[data-evidence-tab]")];
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length];
    event.preventDefault();
    next.focus();
    next.click();
  });
});
