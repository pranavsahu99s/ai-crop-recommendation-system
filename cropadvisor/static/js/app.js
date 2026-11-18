// Small progressive enhancements; every page works without JavaScript.
(function () {
  "use strict";

  // Mobile navigation
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Confirm destructive actions: <form data-confirm="...">
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // Processing indicator while a recommendation is generated (TC-11)
  document.querySelectorAll("form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("button[type=submit]");
      if (!btn || btn.classList.contains("is-busy")) return;
      btn.classList.add("is-busy");
      btn.setAttribute("aria-busy", "true");
      btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>' + form.getAttribute("data-busy");
      setTimeout(function () { btn.disabled = true; }, 0);
    });
  });

  // Fill typical soil values for the selected soil type (farm form)
  var fillBtn = document.getElementById("fill-typical");
  var soilSelect = document.getElementById("soil_type");
  var soilData = document.getElementById("soil-data");
  if (fillBtn && soilSelect && soilData) {
    var soils = JSON.parse(soilData.textContent);
    var updateBtn = function () { fillBtn.disabled = !soils[soilSelect.value]; };
    soilSelect.addEventListener("change", updateBtn);
    updateBtn();
    fillBtn.addEventListener("click", function () {
      var s = soils[soilSelect.value];
      if (!s) return;
      ["n", "p", "k", "ph"].forEach(function (key) {
        var input = document.getElementById(key);
        if (input && input.value.trim() === "") input.value = s[key];
      });
      var note = document.getElementById("fill-note");
      if (note) note.hidden = false;
    });
  }
})();
