(function() {
    const originalSetTimeout = window.setTimeout;
    const originalSetInterval = window.setInterval;
    window.speedMultiplier = 1;

    // Ghi đè setTimeout
    window.setTimeout = function(handler, delay, ...args) {
        const adjustedDelay = delay / window.speedMultiplier;
        console.log(`[Timer] setTimeout detected: ${delay}ms -> ${Math.round(adjustedDelay)}ms`);
        return originalSetTimeout(handler, adjustedDelay, ...args);
    };

    // Ghi đè setInterval
    window.setInterval = function(handler, delay, ...args) {
        const adjustedDelay = delay / window.speedMultiplier;
        console.log(`[Timer] setInterval detected: ${delay}ms -> ${Math.round(adjustedDelay)}ms`);
        return originalSetInterval(handler, adjustedDelay, ...args);
    };

    // Lắng nghe sự kiện đổi tốc độ từ giao diện
    window.addEventListener("message", (event) => {
        if (event.data.type === "CHANGE_SPEED") {
            window.speedMultiplier = event.data.value;
            console.log(`[System] Speed changed to: ${window.speedMultiplier}x`);
        }
    });
})();
