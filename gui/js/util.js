/**
 * 公共工具（转义等）：原先散落在各文件里的重复实现统一到此处。
 * 必须在其它 js 之前加载。
 */
var U = {
    /* 文本转义。引号也一起转 —— HTML 实体会在文本节点里还原，所以放进正文没有副作用，
       但这样一来这个函数放进 value="..." / placeholder="..." 也是安全的。
       （历史上只转 & < >，配置里任何一个带引号的值就会把属性提前闭合并让整块表单错位。） */
    esc: function (s) {
    return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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