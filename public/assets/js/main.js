(function () {
  const header = document.querySelector("[data-header]");
  const toggle = document.querySelector("[data-menu-toggle]");
  const nav = document.querySelector("[data-nav]");
  const year = document.querySelector("[data-year]");

  if (year) {
    year.textContent = String(new Date().getFullYear());
  }

  if (toggle && header) {
    toggle.addEventListener("click", () => {
      const isOpen = header.classList.toggle("menu-open");
      document.body.classList.toggle("menu-open", isOpen);
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  if (nav && header && toggle) {
    nav.addEventListener("click", (event) => {
      if (event.target instanceof HTMLAnchorElement) {
        header.classList.remove("menu-open");
        document.body.classList.remove("menu-open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  const sections = Array.from(document.querySelectorAll("main section[id]"));
  const links = Array.from(document.querySelectorAll(".site-nav a"));
  if ("IntersectionObserver" in window && sections.length && links.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        const active = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!active) {
          return;
        }
        links.forEach((link) => {
          link.classList.toggle("active", link.getAttribute("href") === `#${active.target.id}`);
        });
      },
      { rootMargin: "-25% 0px -60% 0px", threshold: [0.1, 0.25, 0.5] },
    );
    sections.forEach((section) => observer.observe(section));
  }
})();
