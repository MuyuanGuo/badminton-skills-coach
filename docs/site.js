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
