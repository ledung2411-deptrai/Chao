// 1. Inject script "hack" thời gian vào trang web
const script = document.createElement('script');
script.src = chrome.runtime.getURL('inject.js');
(document.head || document.documentElement).appendChild(script);

// 2. Tạo giao diện Overlay
const ui = document.createElement('div');
ui.style = `
    position: fixed; top: 10px; right: 10px; z-index: 9999;
    background: rgba(0,0,0,0.8); color: white; padding: 15px;
    border-radius: 8px; font-family: monospace; font-size: 12px;
    width: 250px; box-shadow: 0 4px 15px rgba(0,0,0,0.5);
`;
ui.innerHTML = `
    <h4 style="margin:0 0 10px 0">Master Tool Control</h4>
    <div>Speed: <span id="speedVal">1</span>x</div>
    <input type="range" id="speedRange" min="1" max="10" step="0.5" value="1" style="width:100%">
    <hr>
    <div>Auto Click Selector:</div>
    <input type="text" id="selectorInput" placeholder=".btn-confirm" style="width:100%; color:black">
    <div id="statusLog" style="margin-top:10px; height:60px; overflow-y:auto; color:#0f0">Status: Ready</div>
`;
document.body.appendChild(ui);

// 3. Xử lý sự kiện UI
const speedRange = ui.querySelector('#speedRange');
const speedVal = ui.querySelector('#speedVal');
const selectorInput = ui.querySelector('#selectorInput');
const statusLog = ui.querySelector('#statusLog');

speedRange.addEventListener('input', (e) => {
    const val = e.target.value;
    speedVal.innerText = val;
    window.postMessage({ type: "CHANGE_SPEED", value: parseFloat(val) }, "*");
});

// 4. Automation Logic: Tự động click
setInterval(() => {
    const selector = selectorInput.value;
    if (selector) {
        const element = document.querySelector(selector);
        if (element) {
            statusLog.innerText = `[Action] Found & Clicking: ${selector}`;
            element.click();
        } else {
            statusLog.innerText = `[Searching] ${selector}...`;
        }
    }
}, 1000); // Check mỗi giây một lần (cũng bị ảnh hưởng bởi speedMultiplier)
