(function () {
  'use strict';
  var labels = {
    '#header-back-to-top a': '返回首页',
    '#header-rom-change a[href*="register"], .member-info-rom-register': '登记游戏卡',
    '#header-rom-change a[href*="change"], .member-info-rom-change': '切换游戏卡',
    '.dialog-buttons-ok': '确定', '.dialog-buttons-cancel': '取消', '.dialog-buttons-register': '登记',
    '.dialog-buttons-close': '关闭', '.dialog-buttons-back': '返回', '.dialog-buttons-next': '下一步',
    '.dialog-buttons-change': '切换', '.dialog-buttons-yes': '是', '.dialog-buttons-no': '否'
  };
  var matches = Object.keys(labels).join(',');
  function update(node) {
    if (node.nodeType !== 1) return;
    if (node.matches(matches)) {
      for (var selector in labels) {
        if (node.matches(selector) && !node.textContent.trim()) {
          node.textContent = labels[selector];
          break;
        }
      }
    }
    var candidates = node.matches('img[alt]') ? [node] : [];
    candidates.forEach(function (img) {
      var alt = img.alt.trim();
      var src = img.getAttribute('src') || '';
      if (!alt || !/[\u4e00-\u9fff]/.test(alt) ||
          !/(?:navi|imgtext|btn|button|title|ttl|h[1-4][_-])/i.test(src)) return;
      var label = document.createElement('span');
      label.className = img.closest('a') ? 'zh-image-button' : 'zh-image-text';
      label.textContent = alt;
      if (img.getAttribute('width')) label.style.width = img.getAttribute('width') + 'px';
      if (img.getAttribute('height')) label.style.minHeight = img.getAttribute('height') + 'px';
      img.replaceWith(label);
    });
  }
  function scan(node) {
    update(node);
    if (node.querySelectorAll) node.querySelectorAll(matches + ',img[alt]').forEach(update);
  }
  scan(document.body);
  new MutationObserver(function (records) {
    records.forEach(function (record) {
      if (record.type === 'attributes') update(record.target);
      else record.addedNodes.forEach(scan);
    });
  }).observe(document.body, {subtree:true, childList:true, attributes:true, attributeFilter:['href','class']});
}());
