// src/drone_visualizer/static/js/main.js
let scene, camera, renderer, controls, drone, pathPoints = [];
let animationId = null, clock = new THREE.Clock();
let currentWaypointIndex = 0, isPlaying = false, animationSpeed = 1.0;
let waypoints = [];

function initVisualization() {
    // 1. 创建场景
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);
    
    // 2. 创建相机
    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(CONFIG.cameraPosition.x, CONFIG.cameraPosition.y, CONFIG.cameraPosition.z);
    
    // 3. 创建渲染器
    const container = document.getElementById('scene-container');
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);
    
    // 4. 添加轨道控制
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    
    // 5. 添加灯光
    const ambientLight = new THREE.AmbientLight(0x404040, 0.6);
    scene.add(ambientLight);
    
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(50, 100, 50);
    directionalLight.castShadow = true;
    scene.add(directionalLight);
    
    // 6. 添加网格地面
    const gridHelper = new THREE.GridHelper(CONFIG.gridSize, 20, 0x444444, 0x222222);
    scene.add(gridHelper);
    
    // 7. 添加坐标系
    const axesHelper = new THREE.AxesHelper(20);
    scene.add(axesHelper);
    
    // 8. 处理路径数据
    processPathData();
    
    // 9. 加载无人机模型
    loadDroneModel();
    
    // 10. 初始化路径点列表
    initPathPointsList();
    
    // 11. 开始动画循环
    animate();
    
    // 12. 窗口大小调整处理
    window.addEventListener('resize', onWindowResize);
}

function processPathData() {
    // 解析路径数据
    const path = PATH_DATA.path || [];
    waypoints = PATH_DATA.waypoints || [];
    
    // 创建路径线
    if (path.length > 1) {
        const points = path.map(p => new THREE.Vector3(p.x, p.z, p.y)); // 注意：Three.js中Y是高度
        const lineGeometry = new THREE.BufferGeometry().setFromPoints(points);
        const lineMaterial = new THREE.LineBasicMaterial({ 
            color: CONFIG.pathColor,
            linewidth: 3
        });
        const pathLine = new THREE.Line(lineGeometry, lineMaterial);
        scene.add(pathLine);
        
        // 添加路径点球体
        path.forEach((point, index) => {
            const sphereGeometry = new THREE.SphereGeometry(1, 16, 16);
            const sphereMaterial = new THREE.MeshBasicMaterial({ 
                color: index === 0 ? 0x00ff00 : (index === path.length-1 ? 0xff0000 : 0xffff00)
            });
            const sphere = new THREE.Mesh(sphereGeometry, sphereMaterial);
            sphere.position.set(point.x, point.z, point.y);
            scene.add(sphere);
            
            // 添加标签
            addLabel(sphere.position, `P${index+1}: ${point.action}`);
        });
    }
}

function loadDroneModel() {
    // 使用占位几何体（实际应加载GLTF模型）
    const geometry = new THREE.BoxGeometry(3, 1, 3);
    const material = new THREE.MeshPhongMaterial({ 
        color: 0x3498db,
        emissive: 0x072534,
        side: THREE.DoubleSide,
        flatShading: true
    });
    
    drone = new THREE.Mesh(geometry, material);
    drone.castShadow = true;
    
    // 添加螺旋桨
    const propellerGeometry = new THREE.CylinderGeometry(0.2, 0.2, 0.1, 8);
    const propellerMaterial = new THREE.MeshPhongMaterial({ color: 0x2c3e50 });
    
    for (let i = 0; i < 4; i++) {
        const propeller = new THREE.Mesh(propellerGeometry, propellerMaterial);
        const angle = (i * Math.PI) / 2;
        const radius = 2;
        propeller.position.set(
            Math.cos(angle) * radius,
            0.5,
            Math.sin(angle) * radius
        );
        drone.add(propeller);
    }
    
    // 初始位置
    if (PATH_DATA.path && PATH_DATA.path.length > 0) {
        const startPoint = PATH_DATA.path[0];
        drone.position.set(startPoint.x, startPoint.z, startPoint.y);
    }
    
    scene.add(drone);
}

function addLabel(position, text) {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    context.font = 'Bold 20px Arial';
    const textWidth = context.measureText(text).width;
    
    canvas.width = textWidth + 20;
    canvas.height = 30;
    context = canvas.getContext('2d');
    context.font = 'Bold 20px Arial';
    context.fillStyle = 'rgba(255, 255, 255, 0.8)';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = 'black';
    context.fillText(text, 10, 22);
    
    const texture = new THREE.CanvasTexture(canvas);
    const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
    const sprite = new THREE.Sprite(spriteMaterial);
    sprite.position.set(position.x, position.y + 3, position.z);
    sprite.scale.set(canvas.width / 10, canvas.height / 10, 1);
    scene.add(sprite);
}

function initPathPointsList() {
    const container = document.getElementById('path-points-list');
    PATH_DATA.path.forEach((point, index) => {
        const div = document.createElement('div');
        div.className = 'path-point';
        div.innerHTML = `
            <strong>P${index+1}</strong> (${point.x}, ${point.y}, ${point.z})<br>
            <small>朝向: ${point.yaw}° | 动作: ${point.action}</small>
        `;
        div.onclick = () => focusOnPoint(point);
        container.appendChild(div);
    });
}

function focusOnPoint(point) {
    camera.position.set(point.x + 20, point.z + 20, point.y + 20);
    camera.lookAt(new THREE.Vector3(point.x, point.z, point.y));
    controls.target.set(point.x, point.z, point.y);
}

function playAnimation() {
    if (isPlaying) return;
    isPlaying = true;
    document.getElementById('play-btn').disabled = true;
    document.getElementById('pause-btn').disabled = false;
    animateDrone();
}

function pauseAnimation() {
    isPlaying = false;
    document.getElementById('play-btn').disabled = false;
    document.getElementById('pause-btn').disabled = true;
}

function resetAnimation() {
    currentWaypointIndex = 0;
    if (PATH_DATA.path && PATH_DATA.path.length > 0) {
        const startPoint = PATH_DATA.path[0];
        drone.position.set(startPoint.x, startPoint.z, startPoint.y);
    }
    pauseAnimation();
    updateHUD();
}

function changeSpeed(value) {
    animationSpeed = parseFloat(value);
    document.getElementById('speed-value').textContent = value + 'x';
}

function animateDrone() {
    if (!isPlaying || waypoints.length === 0) return;
    
    const delta = clock.getDelta() * animationSpeed;
    currentWaypointIndex = (currentWaypointIndex + delta * 10) % waypoints.length;
    
    const waypointIndex = Math.floor(currentWaypointIndex);
    const nextIndex = (waypointIndex + 1) % waypoints.length;
    const t = currentWaypointIndex - waypointIndex;
    
    if (waypointIndex < waypoints.length - 1) {
        const current = waypoints[waypointIndex];
        const next = waypoints[nextIndex];
        
        drone.position.x = current.x + (next.x - current.x) * t;
        drone.position.y = current.z + (next.z - current.z) * t; // Y是高度
        drone.position.z = current.y + (next.y - current.y) * t;
        
        // 更新螺旋桨旋转
        drone.children.forEach((propeller, i) => {
            propeller.rotation.y += 0.5 * animationSpeed;
        });
    }
    
    updateHUD();
    requestAnimationFrame(animateDrone);
}

function updateHUD() {
    const posEl = document.getElementById('drone-pos');
    const speedEl = document.getElementById('drone-speed');
    const statusEl = document.getElementById('drone-status');
    
    posEl.textContent = `(${drone.position.x.toFixed(1)}, ${drone.position.z.toFixed(1)}, ${drone.position.y.toFixed(1)})`;
    speedEl.textContent = animationSpeed.toFixed(1) + ' m/s';
    statusEl.textContent = isPlaying ? '飞行中' : '就绪';
}

function onWindowResize() {
    const container = document.getElementById('scene-container');
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
}

function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
}

// 全局函数供按钮调用
window.playAnimation = playAnimation;
window.pauseAnimation = pauseAnimation;
window.resetAnimation = resetAnimation;
window.changeSpeed = changeSpeed;
window.resetCamera = function() {
    camera.position.set(CONFIG.cameraPosition.x, CONFIG.cameraPosition.y, CONFIG.cameraPosition.z);
    controls.target.set(0, 0, 0);
};