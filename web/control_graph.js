// Follow the selected control socket only, including native ComfyUI subgraph inputs.
// API reference: Comfy-Org/ComfyUI_frontend SubgraphNode._subgraphSlot and SubgraphInput.linkIds.
export function connectedModels(controller, inputName = 'download_control') {
    const visited = new WeakMap();
    const models = new Set();
    function readLink(graph, id) {
        return graph.getLink?.(id) ?? graph.links?.get?.(id) ?? graph.links?.[id];
    }
    function walk(graph, linkId, depth = 0) {
        if (!graph || depth > 64) throw new Error('Control wiring is too deeply nested.');
        let ids = visited.get(graph);
        if (!ids) { ids = new Set(); visited.set(graph, ids); }
        if (ids.has(linkId)) return;
        ids.add(linkId);
        const link = readLink(graph, linkId);
        if (!link) throw new Error('A control link is missing. Reconnect the cable.');
        const target = graph.getNodeById(link.target_id);
        if (!target) throw new Error('Cannot resolve a control target. Keep the controllers outside the model subgraph.');
        if (target.mode === 2 || target.mode === 4) return;
        if (target.type === 'OrelsModelDownload' || target.comfyClass === 'OrelsModelDownload') {
            if (target.inputs?.[link.target_slot]?.name !== inputName) {
                throw new Error(`Connect to ${inputName} on Model's Download.`);
            }
            models.add(target);
            return;
        }
        if (target.subgraph) {
            const slot = target.inputs?.[link.target_slot];
            const internal = slot?._subgraphSlot ?? target.subgraph.inputNode?.slots?.[link.target_slot];
            if (!internal?.linkIds) throw new Error('Subgraph input cannot be resolved. Reconnect its internal control socket.');
            for (const id of internal.linkIds) walk(target.subgraph, id, depth + 1);
            return;
        }
        if (target.type === 'Reroute') {
            for (const id of target.outputs?.[0]?.links || []) walk(graph, id, depth + 1);
            return;
        }
        throw new Error('This control connection must lead to Model\'s Download or a native Subgraph containing it.');
    }
    for (const id of controller.outputs?.[0]?.links || []) walk(controller.graph, id);
    return [...models];
}
