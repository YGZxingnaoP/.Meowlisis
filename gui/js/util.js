/**
 * 公共工具（转义等）：原先散落在各文件里的重复实现统一到此处。
 * 必须在其它 js 之前加载。
 */
var U = {
    esc: function (s) {
    return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
    },
    escAttr: function (s) {
    return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
    },
};
window.U = U;