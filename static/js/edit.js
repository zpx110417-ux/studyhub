/* 编辑器脚本：实时预览（marked + DOMPurify）、Markdown 工具栏、图片/附件上传。
   依赖 static/vendor/ 下的 marked.min.js 与 purify.min.js；
   若二者缺失则预览降级为纯文本显示，不影响保存。 */
(function () {
  var ta = document.getElementById("content");
  var preview = document.getElementById("preview");
  if (!ta || !preview) return;

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.content : "";
  var hasMarked = typeof marked !== "undefined" && marked.parse;
  var hasPurify = typeof DOMPurify !== "undefined";

  function render() {
    if (hasMarked) {
      var html = marked.parse(ta.value);
      preview.innerHTML = hasPurify ? DOMPurify.sanitize(html) : html;
    } else {
      preview.textContent = ta.value;
    }
  }

  var timer = null;
  ta.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(render, 300);
  });
  render();

  // ---------- 工具栏 ----------
  function wrap(before, after) {
    var s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.slice(s, e) || "文本";
    ta.setRangeText(before + sel + after, s, e, "end");
    ta.focus();
    ta.dispatchEvent(new Event("input"));
  }
  var MAP = {
    bold: ["**", "**"], italic: ["*", "*"], code: ["`", "`"],
    h2: ["\n## ", "\n"], quote: ["> ", "\n"],
    ul: ["\n- ", ""], ol: ["\n1. ", ""], link: ["[", "](https://)"]
  };
  document.querySelectorAll("[data-md]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var m = MAP[btn.getAttribute("data-md")];
      if (m) wrap(m[0], m[1]);
    });
  });

  // ---------- 图片 / 附件上传 ----------
  function upload(input, url) {
    if (!input.files.length) return;
    var fd = new FormData();
    fd.append("file", input.files[0]);
    fd.append("csrf_token", csrf);
    fetch(url, { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, j: j }; });
      })
      .then(function (res) {
        if (res.ok && res.j.markdown) {
          var pos = ta.selectionEnd;
          ta.setRangeText("\n" + res.j.markdown + "\n", pos, pos, "end");
          ta.dispatchEvent(new Event("input"));
        } else {
          alert(res.j.error || "上传失败，请重试。");
        }
      })
      .catch(function () { alert("上传失败，请检查网络。"); });
    input.value = "";
  }
  var imgInput = document.getElementById("upload-image");
  var fileInput = document.getElementById("upload-file");
  if (imgInput) imgInput.addEventListener("change", function () { upload(imgInput, "/upload/image"); });
  if (fileInput) fileInput.addEventListener("change", function () { upload(fileInput, "/upload/file"); });
})();
