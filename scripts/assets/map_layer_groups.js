// Keep Leaflet's inputs and events; rebuild nested groups after its label refresh.
(function () {
    const collapsed = {};
    function groupControl() {
        const container = document.querySelector('.leaflet-control-layers-overlays');
        if (!container) return;
        const synchronizers = [];
        function group(parent, id, name, matches, prefix) {
            const children = Array.from(parent.children).filter(matches);
            if (!children.length) return null;
            const section = document.createElement('section');
            const header = document.createElement('div');
            const master = document.createElement('button');
            master.type = 'button';
            master.setAttribute('role', 'checkbox');
            master.setAttribute('aria-label', name);
            const title = document.createElement('span');
            title.textContent = ' ' + name;
            title.style.fontWeight = 'bold';
            const button = document.createElement('button');
            button.type = 'button';
            button.style.marginLeft = '12px';
            const body = document.createElement('div');
            body.id = 'layers-' + id;
            body.style.paddingLeft = '18px';
            body.hidden = Boolean(collapsed[id]);
            function disclosure() {
                button.textContent = body.hidden ? 'Mở danh sách' : 'Thu gọn';
                button.setAttribute('aria-controls', body.id);
                button.setAttribute('aria-expanded', String(!body.hidden));
                button.setAttribute('aria-label', button.textContent + ' ' + name);
            }
            parent.insertBefore(section, children[0]);
            header.append(master, title, button);
            section.append(header, body);
            children.forEach(function (child) {
                if (prefix) {
                    const walker = document.createTreeWalker(child, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        walker.currentNode.textContent = walker.currentNode.textContent.replace(prefix, '').trim();
                    }
                }
                body.append(child);
            });
            const inputs = Array.from(body.querySelectorAll('input'));
            function sync() {
                const count = inputs.filter(function (input) { return input.checked; }).length;
                master.setAttribute('aria-checked', count === inputs.length ? 'true' : count ? 'mixed' : 'false');
                master.textContent = count === inputs.length ? '☑' : count ? '−' : '☐';
            }
            synchronizers.push(sync);
            master.addEventListener('click', function () {
                const checked = master.getAttribute('aria-checked') !== 'true';
                inputs.forEach(function (input) {
                    // Leaflet replaces input elements after each click; resolve the current one by ID.
                    const current = Array.from(container.querySelectorAll('input')).find(function (item) {
                        return item.layerId === input.layerId;
                    });
                    if (current && current.checked !== checked) current.click();
                });
            });
            button.addEventListener('click', function () {
                body.hidden = !body.hidden;
                collapsed[id] = body.hidden;
                disclosure();
            });
            disclosure();
            sync();
            return body;
        }
        ['MAP-1', 'MAP-2'].forEach(function (name) {
            const id = name.toLowerCase();
            const body = group(container, id, name, function (label) {
                return label.tagName === 'LABEL' && label.textContent.trim().startsWith(name + ':');
            }, name + ':');
            if (!body) return;
            if (name === 'MAP-1') {
                group(body, id + '-population', 'Dân số / xã phường', function (label) {
                    return /^(Population|Commune)/.test(label.textContent.trim());
                });
                const routes = group(body, id + '-routes', 'Đường phân bổ', function (label) {
                    return label.textContent.trim().startsWith('Route ');
                }, 'Route ');
                if (routes) ['primary', 'secondary'].forEach(function (kind) {
                    group(routes, id + '-routes-' + kind, kind === 'primary' ? 'Tuyến chính' : 'Tuyến phụ', function (label) {
                        return label.textContent.trim().startsWith(kind + ' ·');
                    }, kind + ' ·');
                });
                group(body, id + '-facilities', 'Cơ sở y tế', function (label) {
                    return label.textContent.trim().startsWith('Facility —');
                }, 'Facility —');
            } else {
                group(body, id + '-children', 'Trẻ 5–14 tuổi', function (label) {
                    return label.textContent.trim().startsWith('Children');
                });
                group(body, id + '-schools', 'Trường học', function (label) {
                    return label.textContent.trim().startsWith('Schools');
                });
            }
        });
        container.onchange = function () { synchronizers.forEach(function (sync) { sync(); }); };
    }
    const update = L.Control.Layers.prototype._update;
    L.Control.Layers.prototype._update = function () {
        const result = update.apply(this, arguments);
        groupControl();
        return result;
    };
    groupControl();
}());
