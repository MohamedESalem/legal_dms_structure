/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

class DmsDirectoryExplorerAction extends Component {
    static template = "legal_dms_structure.DmsDirectoryExplorerAction";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.selectNode = this.selectNode.bind(this);
        this.toggleNode = this.toggleNode.bind(this);
        this.createRootFolder = this.createRootFolder.bind(this);
        this.createSubfolder = this.createSubfolder.bind(this);
        this.renameSelected = this.renameSelected.bind(this);
        this.deleteSelected = this.deleteSelected.bind(this);
        this.refreshTree = this.refreshTree.bind(this);
        this.state = useState({
            loading: true,
            selectedId: null,
            nodesById: {},
            childrenByParent: {},
            expandedById: {},
        });
        onWillStart(async () => {
            await this.reloadTree();
        });
    }

    async reloadTree(preferredSelectedId = null) {
        this.state.loading = true;
        try {
            const records = await this.orm.searchRead(
                "dms.directory.template",
                [["active", "=", true]],
                ["name", "parent_id", "level", "usage", "sequence", "complete_name"],
                { order: "sequence,id" }
            );
            const clientsRoot = records.find((record) => record.usage === "clients_root");
            const clientsRootId = clientsRoot ? clientsRoot.id : null;
            const normalized = records.map((record) => this._normalizeNode(record, clientsRootId));
            const { nodesById, childrenByParent } = this._buildTreeIndex(normalized);
            this.state.nodesById = nodesById;
            this.state.childrenByParent = childrenByParent;
            this.state.expandedById = this._nextExpandedState(childrenByParent, this.state.expandedById);
            this.state.selectedId = this._resolveSelection(preferredSelectedId);
        } catch {
            this.notification.add("Unable to load directory tree.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    _normalizeNode(record, clientsRootId) {
        const actualParentId = record.parent_id ? record.parent_id[0] : null;
        const displayUnderClients =
            (record.usage === "cases_container" || record.usage === "subjects_container") &&
            !actualParentId &&
            clientsRootId;
        return {
            id: record.id,
            name: record.name,
            parentId: actualParentId,
            treeParentId: displayUnderClients ? clientsRootId : actualParentId,
            level: record.level,
            usage: record.usage,
            sequence: record.sequence || 0,
            completeName: record.complete_name || record.name,
        };
    }

    _buildTreeIndex(nodes) {
        const nodesById = {};
        const childrenByParent = {};
        for (const node of nodes) {
            nodesById[node.id] = node;
            const key = this._parentKey(node.treeParentId);
            if (!childrenByParent[key]) {
                childrenByParent[key] = [];
            }
            childrenByParent[key].push(node);
        }
        for (const key of Object.keys(childrenByParent)) {
            childrenByParent[key].sort((left, right) => {
                if (left.sequence !== right.sequence) {
                    return left.sequence - right.sequence;
                }
                return left.id - right.id;
            });
        }
        return { nodesById, childrenByParent };
    }

    _nextExpandedState(childrenByParent, previousExpanded) {
        const nextExpanded = { ...previousExpanded };
        for (const rootNode of childrenByParent[this._parentKey(null)] || []) {
            if (nextExpanded[rootNode.id] === undefined) {
                nextExpanded[rootNode.id] = true;
            }
        }
        return nextExpanded;
    }

    _parentKey(parentId) {
        return parentId === null ? "root" : String(parentId);
    }

    _childrenOfParent(parentId) {
        return this.state.childrenByParent[this._parentKey(parentId)] || [];
    }

    get selectedNode() {
        return this.state.selectedId ? this.state.nodesById[this.state.selectedId] : null;
    }

    get visibleNodes() {
        const output = [];
        const visit = (parentId, depth) => {
            for (const node of this._childrenOfParent(parentId)) {
                const children = this._childrenOfParent(node.id);
                output.push({
                    id: node.id,
                    depth,
                    name: node.name,
                    usage: node.usage,
                    hasChildren: children.length > 0,
                    isExpanded: Boolean(this.state.expandedById[node.id]),
                });
                if (children.length && this.state.expandedById[node.id]) {
                    visit(node.id, depth + 1);
                }
            }
        };
        visit(null, 0);
        return output;
    }

    get selectedChildren() {
        if (!this.selectedNode) {
            return [];
        }
        return this._childrenOfParent(this.selectedNode.id);
    }

    selectNode(nodeId) {
        this.state.selectedId = nodeId;
    }

    toggleNode(nodeId) {
        this.state.expandedById = {
            ...this.state.expandedById,
            [nodeId]: !this.state.expandedById[nodeId],
        };
    }

    async createRootFolder() {
        await this._openCreateDialog(null);
    }

    async createSubfolder() {
        if (!this.selectedNode) {
            this.notification.add("Select a folder before creating a subfolder.", { type: "warning" });
            return;
        }
        await this._openCreateDialog(this.selectedNode);
    }

    async renameSelected() {
        if (!this.selectedNode) {
            this.notification.add("Select a folder before renaming.", { type: "warning" });
            return;
        }
        const selectedId = this.selectedNode.id;
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "Rename Folder",
                res_model: "dms.directory.template",
                res_id: selectedId,
                views: [[false, "form"]],
                target: "new",
            },
            {
                onClose: async () => {
                    await this.reloadTree(selectedId);
                },
            }
        );
    }

    async refreshTree() {
        await this.reloadTree(this.state.selectedId);
    }

    isProtectedNode(node) {
        if (!node) {
            return false;
        }
        return ["clients_root", "archive_root", "cases_container", "subjects_container"].includes(
            node.usage
        );
    }

    get canDeleteSelected() {
        return Boolean(this.selectedNode) && !this.isProtectedNode(this.selectedNode);
    }

    async deleteSelected() {
        const node = this.selectedNode;
        if (!node) {
            this.notification.add("Select a folder before deleting.", { type: "warning" });
            return;
        }
        if (this.isProtectedNode(node)) {
            this.notification.add("This folder is system-protected and cannot be deleted.", {
                type: "warning",
            });
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Delete Folder",
            body: `Delete "${node.name}" and all its subfolders? This action cannot be undone.`,
            confirmLabel: "Delete",
            confirmClass: "btn-danger",
            confirm: async () => {
                try {
                    await this.orm.unlink("dms.directory.template", [node.id]);
                    await this.reloadTree(this._nextSelectionAfterDelete(node));
                    this.notification.add("Folder deleted successfully.", { type: "success" });
                } catch {
                    this.notification.add("Unable to delete this folder.", { type: "danger" });
                }
            },
            cancelLabel: "Cancel",
        });
    }

    _nextSelectionAfterDelete(node) {
        const siblings = this._childrenOfParent(node.treeParentId).filter((item) => item.id !== node.id);
        if (siblings.length) {
            return siblings[0].id;
        }
        if (node.treeParentId && this.state.nodesById[node.treeParentId]) {
            return node.treeParentId;
        }
        const roots = this._childrenOfParent(null);
        return roots.length ? roots[0].id : null;
    }

    _resolveSelection(preferredSelectedId = null) {
        if (preferredSelectedId && this.state.nodesById[preferredSelectedId]) {
            return preferredSelectedId;
        }
        if (this.state.selectedId && this.state.nodesById[this.state.selectedId]) {
            return this.state.selectedId;
        }
        const roots = this._childrenOfParent(null);
        return roots.length ? roots[0].id : null;
    }

    async _openCreateDialog(parentNode) {
        const selectedIdBeforeOpen = this.state.selectedId;
        const context = {
            default_usage: "normal",
        };
        if (parentNode) {
            context.default_parent_id = parentNode.id;
            context.default_level = parentNode.level;
        }
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: parentNode ? "New Subfolder" : "New Folder",
                res_model: "dms.directory.template",
                views: [[false, "form"]],
                target: "new",
                context,
            },
            {
                onClose: async () => {
                    await this.reloadTree(parentNode ? parentNode.id : selectedIdBeforeOpen);
                },
            }
        );
    }

    usageLabel(usage) {
        if (usage === "clients_root" || usage === "archive_root") {
            return "System Root";
        }
        if (usage === "cases_container" || usage === "subjects_container") {
            return "Auto Container";
        }
        return "Standard";
    }
}

registry.category("actions").add(
    "legal_dms_structure.dms_directory_template_explorer",
    DmsDirectoryExplorerAction
);
