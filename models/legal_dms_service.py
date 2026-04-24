from collections import defaultdict

from lxml import etree

from odoo import _, models, Command
from odoo.addons.dms.tools.file import unique_name
from odoo.exceptions import UserError


class LegalDmsService(models.AbstractModel):
    _name = "legal.dms.service"
    _description = "Legal DMS Service"

    _BUTTON_GROUPS = ",".join(
        [
            "legal_dms_structure.group_legal_dms_admin",
            "legal_dms_structure.group_legal_dms_lawyer",
            "legal_dms_structure.group_legal_dms_staff",
        ]
    )
    _ASSIGNEE_MULTI_FIELDS = ("user_ids", "member_ids", "collaborator_ids")
    _CLIENT_ROOT_NAME = "Clients"
    _ARCHIVE_ROOT_NAME = "Archive"
    _SMART_BUTTON_VIEW_SPECS = {
        "res.partner": {
            "view_xmlid": "legal_dms_structure.view_partner_form_legal_dms_smart_buttons",
        },
        "project.project": {
            "view_xmlid": "legal_dms_structure.view_project_form_legal_dms_smart_buttons",
        },
    }

    def _directory_model(self):
        return self.env["dms.directory"].sudo().with_context(
            legal_dms_allow_structure_write=True,
            tracking_disable=True,
            mail_create_nolog=True,
        )

    def _access_group_model(self):
        return self.env["dms.access.group"].sudo().with_context(
            tracking_disable=True,
        )

    def _template_model(self):
        return self.env["dms.directory.template"].sudo()

    def _special_template(self, usage):
        return self._template_model().search(
            [("active", "=", True), ("usage", "=", usage)],
            order="sequence, id",
            limit=1,
        )

    def _record_write(self, record, vals):
        if not vals:
            return
        record.sudo().with_context(
            skip_legal_dms_sync=True,
            tracking_disable=True,
        ).write(vals)

    def _get_storage(self, raise_if_missing=True):
        storage_id = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("legal_dms_structure.legal_dms_storage_id")
        )
        storage = self.env["dms.storage"].browse(int(storage_id or 0)).exists()
        if not storage and raise_if_missing:
            raise UserError(
                _(
                    "Configure a Legal DMS storage first from Settings before creating managed legal folders."
                )
            )
        return storage

    def _get_admin_group(self):
        return self.env.ref("legal_dms_structure.group_legal_dms_admin")

    def _get_admin_directory_access_group(self):
        return self.env.ref("legal_dms_structure.dms_access_group_legal_dms_admin")

    def _get_project_assignment_field_names(self):
        field_names = []
        project_model = self.env["project.project"]
        if (
            "user_id" in project_model._fields
            and project_model._fields["user_id"].comodel_name == "res.users"
        ):
            field_names.append("user_id")
        for field_name in self._ASSIGNEE_MULTI_FIELDS:
            field = project_model._fields.get(field_name)
            if not field or field.type not in {"many2many", "one2many"}:
                continue
            if field.comodel_name == "res.users":
                field_names.append(field_name)
                continue
            comodel = self.env[field.comodel_name]
            user_field = comodel._fields.get("user_id")
            if user_field and user_field.comodel_name == "res.users":
                field_names.append(field_name)
        return tuple(field_names)

    def _is_client_partner(self, partner):
        return bool(partner and partner.exists() and not partner.parent_id)

    def _is_legal_matter(self, project):
        return bool(
            project
            and project.exists()
            and not getattr(project, "is_template", False)
            and getattr(project, "matter_type", False) in {"case", "subject"}
            and project.partner_id
        )

    def _get_live_directory(self, record):
        directory = self.env["dms.directory"].sudo().search(
            [
                ("legal_record_model", "=", record._name),
                ("legal_record_id", "=", record.id),
                ("legal_archived", "=", False),
            ],
            limit=1,
        )
        if directory:
            return directory
        return self.env["dms.directory"].sudo().search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
            ],
            limit=1,
        )

    def _get_archived_directory(self, record):
        return self.env["dms.directory"].sudo().search(
            [
                ("legal_record_model", "=", record._name),
                ("legal_record_id", "=", record.id),
                ("legal_archived", "=", True),
            ],
            limit=1,
        )

    def _record_has_any_directory(self, record):
        return bool(self._get_live_directory(record) or self._get_archived_directory(record))

    def _sync_directory_fields(self, record):
        vals = {}
        if "dms_directory_id" in record._fields:
            live_directory = self._get_live_directory(record)
            if record.dms_directory_id != live_directory:
                vals["dms_directory_id"] = live_directory.id or False
        if "dms_archived_directory_id" in record._fields:
            archived_directory = self._get_archived_directory(record)
            if record.dms_archived_directory_id != archived_directory:
                vals["dms_archived_directory_id"] = archived_directory.id or False
        self._record_write(record, vals)

    def _root_unique_name(self, storage, desired_name):
        names = storage.root_directory_ids.sudo().mapped("name")
        return unique_name(desired_name, names)

    def _child_unique_name(self, parent_directory, desired_name):
        names = parent_directory.child_directory_ids.sudo().mapped("name")
        return unique_name(desired_name, names)

    def _directory_create(self, vals):
        return self._directory_model().create(vals)

    def _directory_write(self, directory, vals):
        if directory:
            directory.sudo().with_context(
                legal_dms_allow_structure_write=True,
                tracking_disable=True,
            ).write(vals)
        return directory

    def _get_root_by_type(self, storage, node_type, default_name):
        usage = {
            "clients_root": "clients_root",
            "archive_root": "archive_root",
        }.get(node_type)
        special_template = self._special_template(usage) if usage else False
        default_name = special_template.name if special_template else default_name
        directory_model = self.env["dms.directory"].sudo()
        directory = directory_model.search(
            [
                ("storage_id", "=", storage.id),
                ("is_root_directory", "=", True),
                ("legal_node_type", "=", node_type),
            ],
            limit=1,
        )
        if not directory:
            directory = directory_model.search(
                [
                    ("storage_id", "=", storage.id),
                    ("is_root_directory", "=", True),
                    ("name", "=", default_name),
                ],
                limit=1,
            )
        if directory:
            self._directory_write(
                directory,
                {
                    "legal_managed": True,
                    "legal_node_type": node_type,
                    "legal_archived": False,
                    "group_ids": [Command.set([self._get_admin_directory_access_group().id])],
                    "inherit_group_ids": False,
                },
            )
            return directory
        return self._directory_create(
            {
                "name": self._root_unique_name(storage, default_name),
                "storage_id": storage.id,
                "is_root_directory": True,
                "legal_managed": True,
                "legal_node_type": node_type,
                "group_ids": [Command.set([self._get_admin_directory_access_group().id])],
                "inherit_group_ids": False,
            }
        )

    def ensure_system_roots(self, storage=False):
        storage = storage or self._get_storage()
        return {
            "clients": self._get_root_by_type(
                storage, "clients_root", self._CLIENT_ROOT_NAME
            ),
            "archive": self._get_root_by_type(
                storage, "archive_root", self._ARCHIVE_ROOT_NAME
            ),
        }

    def _record_access_group_name(self, record):
        prefix = _("Client") if record._name == "res.partner" else _("Matter")
        return _("Legal DMS %(prefix)s Access #%(id)s") % {
            "prefix": prefix,
            "id": record.id,
        }

    def _get_record_access_group(self, record):
        return self._access_group_model().search(
            [("dms_field_ref", "=", f"{record._name},{record.id}")],
            limit=1,
        )

    def _ensure_record_access_group(self, record, explicit_users):
        admin_group = self._get_admin_group()
        values = {
            "name": self._record_access_group_name(record),
            "perm_create": True,
            "perm_write": True,
            "perm_unlink": True,
            "group_ids": [Command.set([admin_group.id])],
            "explicit_user_ids": [Command.set(explicit_users.ids)],
            "dms_field_ref": f"{record._name},{record.id}",
        }
        group = self._get_record_access_group(record)
        if group:
            group.write(values)
            return group
        return self._access_group_model().create(values)

    def _get_project_assignees(self, project):
        users = self.env["res.users"]
        if (
            "user_id" in project._fields
            and project._fields["user_id"].comodel_name == "res.users"
            and project.user_id
        ):
            users |= project.user_id
        for field_name in self._ASSIGNEE_MULTI_FIELDS:
            field = project._fields.get(field_name)
            if not field or field.type not in {"many2many", "one2many"}:
                continue
            records = project[field_name]
            if not records:
                continue
            if field.comodel_name == "res.users":
                users |= records
                continue
            comodel = self.env[field.comodel_name]
            user_field = comodel._fields.get("user_id")
            if user_field and user_field.comodel_name == "res.users":
                users |= records.mapped("user_id")
        return users.filtered(lambda user: user.active)

    def _get_client_assignees(self, partner):
        if not self._is_client_partner(partner):
            return self.env["res.users"]
        domain = [
            ("partner_id", "=", partner.id),
            ("is_template", "=", False),
            ("matter_type", "in", ["case", "subject"]),
        ]
        if "active" in self.env["project.project"]._fields:
            domain.append(("active", "=", True))
        projects = self.env["project.project"].sudo().search(domain)
        users = self.env["res.users"]
        for project in projects:
            users |= self._get_project_assignees(project)
        return users.filtered(lambda user: user.active)

    def _top_level_templates(self, level):
        return self._template_model().search(
            [
                ("active", "=", True),
                ("level", "=", level),
                ("parent_id", "=", False),
                ("usage", "not in", ["clients_root", "archive_root"]),
            ],
            order="sequence, id",
        )

    def _template_children(self, template):
        return template.child_ids.filtered("active").sorted(key=lambda item: (item.sequence, item.id))

    def _directory_node_from_template(self, template):
        if template.level == "client":
            if template.usage == "cases_container":
                return "cases_container"
            if template.usage == "subjects_container":
                return "subjects_container"
            return "client_node"
        if template.level == "case":
            return "case_node"
        return "subject_node"

    def _clone_template_tree(self, template, parent_directory):
        directory = self._directory_create(
            {
                "name": self._child_unique_name(parent_directory, template.name),
                "parent_id": parent_directory.id,
                "legal_managed": True,
                "legal_template_id": template.id,
                "legal_node_type": self._directory_node_from_template(template),
            }
        )
        for child_template in self._template_children(template):
            self._clone_template_tree(child_template, directory)
        return directory

    def _default_container_name(self, usage):
        template = self._special_template(usage)
        if template:
            return template.name
        return _("Cases") if usage == "cases_container" else _("Subjects")

    def _ensure_client_container(self, client_directory, usage):
        node_type = usage
        container = client_directory.child_directory_ids.filtered(
            lambda directory, node_type=node_type: directory.legal_node_type == node_type
        )[:1]
        if container:
            return container
        return self._directory_create(
            {
                "name": self._child_unique_name(
                    client_directory,
                    self._default_container_name(usage),
                ),
                "parent_id": client_directory.id,
                "legal_managed": True,
                "legal_node_type": node_type,
            }
        )

    def _compose_directory_name(self, code, name, fallback):
        name = (name or "").strip()
        if code and name and code != name:
            return f"{code} - {name}"
        return code or name or fallback

    def _partner_sequence_value(self, partner):
        for field_name in ("client_sequence", "partner_sequence"):
            if field_name in partner._fields and partner[field_name]:
                return partner[field_name]
        for sequence_code in ("partner.client_sequence", "partner.code"):
            next_code = self.env["ir.sequence"].sudo().next_by_code(sequence_code)
            if next_code:
                if "client_sequence" in partner._fields and not partner.client_sequence:
                    self._record_write(partner, {"client_sequence": next_code})
                elif "partner_sequence" in partner._fields and not partner.partner_sequence:
                    self._record_write(partner, {"partner_sequence": next_code})
                return next_code
        return False

    def _project_sequence_value(self, project):
        if "sequence_code" in project._fields and project.sequence_code:
            return project.sequence_code
        next_code = self.env["ir.sequence"].sudo().next_by_code("project.sequence")
        if next_code:
            return next_code
        return False

    def _partner_directory_name(self, partner, parent_directory):
        desired_name = self._compose_directory_name(
            self._partner_sequence_value(partner),
            partner.display_name,
            f"CLT-{partner.id:06d}",
        )
        return self._child_unique_name(parent_directory, desired_name)

    def _project_directory_name(self, project, parent_directory):
        fallback_prefix = "CASE" if project.matter_type == "case" else "SUB"
        desired_name = self._compose_directory_name(
            self._project_sequence_value(project),
            project.name,
            f"{fallback_prefix}-{project.id:06d}",
        )
        return self._child_unique_name(parent_directory, desired_name)

    def _linked_record_from_directory(self, directory):
        model_name = directory.legal_record_model or directory.res_model
        record_id = directory.legal_record_id or directory.res_id
        if not model_name or not record_id or model_name not in self.env:
            return self.env["ir.model"]
        return self.env[model_name].browse(record_id).exists()

    def _apply_matter_security(self, root_directory, access_group):
        directories = self.env["dms.directory"].sudo().search(
            [("id", "child_of", root_directory.id)],
            order="parent_path, id",
        )
        for directory in directories:
            if directory == root_directory:
                self._directory_write(
                    directory,
                    {
                        "group_ids": [Command.set([access_group.id])],
                        "inherit_group_ids": False,
                    },
                )
            else:
                self._directory_write(
                    directory,
                    {
                        "group_ids": [Command.clear()],
                        "inherit_group_ids": True,
                    },
                )

    def _apply_client_security(self, root_directory, access_group):
        directories = self.env["dms.directory"].sudo().search(
            [("id", "child_of", root_directory.id)],
            order="parent_path, id",
        )
        for directory in directories:
            if directory == root_directory:
                self._directory_write(
                    directory,
                    {
                        "group_ids": [Command.set([access_group.id])],
                        "inherit_group_ids": False,
                    },
                )
                continue
            if directory.legal_node_type in {"case_root", "subject_root"}:
                linked_record = self._linked_record_from_directory(directory)
                if linked_record and linked_record._name == "project.project":
                    matter_group = self._ensure_record_access_group(
                        linked_record,
                        self._get_project_assignees(linked_record),
                    )
                    self._directory_write(
                        directory,
                        {
                            "group_ids": [Command.set([matter_group.id])],
                            "inherit_group_ids": False,
                        },
                    )
                    continue
            self._directory_write(
                directory,
                {
                    "group_ids": [Command.clear()],
                    "inherit_group_ids": True,
                },
            )

    def _apply_archived_security(self, root_directory):
        directories = self.env["dms.directory"].sudo().search(
            [("id", "child_of", root_directory.id)],
            order="parent_path, id",
        )
        admin_group = self._get_admin_directory_access_group()
        for directory in directories:
            if directory == root_directory:
                self._directory_write(
                    directory,
                    {
                        "group_ids": [Command.set([admin_group.id])],
                        "inherit_group_ids": False,
                    },
                )
            else:
                self._directory_write(
                    directory,
                    {
                        "group_ids": [Command.clear()],
                        "inherit_group_ids": True,
                    },
                )

    def sync_partner_access(self, partners):
        for partner in partners.filtered(self._is_client_partner):
            access_group = self._ensure_record_access_group(
                partner, self._get_client_assignees(partner)
            )
            directory = partner.dms_directory_id or self._get_live_directory(partner)
            if directory:
                self._apply_client_security(directory, access_group)
            self._sync_directory_fields(partner)

    def sync_project_access(self, projects):
        for project in projects.filtered(self._is_legal_matter):
            access_group = self._ensure_record_access_group(
                project, self._get_project_assignees(project)
            )
            directory = project.dms_directory_id or self._get_live_directory(project)
            if directory:
                self._apply_matter_security(directory, access_group)
            self._sync_directory_fields(project)
            self.sync_partner_access(project.partner_id)

    def ensure_partner_directory(self, partner):
        if not self._is_client_partner(partner):
            return self.env["dms.directory"]
        directory = partner.dms_directory_id or self._get_live_directory(partner)
        if directory:
            self._sync_directory_fields(partner)
            self._ensure_client_container(directory, "cases_container")
            self._ensure_client_container(directory, "subjects_container")
            self.sync_partner_access(partner)
            return directory
        roots = self.ensure_system_roots()
        directory = self._directory_create(
            {
                "name": self._partner_directory_name(partner, roots["clients"]),
                "parent_id": roots["clients"].id,
                "legal_managed": True,
                "legal_node_type": "client_root",
                "legal_record_model": partner._name,
                "legal_record_id": partner.id,
                "res_model": partner._name,
                "res_id": partner.id,
            }
        )
        for template in self._top_level_templates("client"):
            self._clone_template_tree(template, directory)
        self._ensure_client_container(directory, "cases_container")
        self._ensure_client_container(directory, "subjects_container")
        self._record_write(partner, {"dms_directory_id": directory.id})
        self.sync_partner_access(partner)
        return directory

    def _matter_template_level(self, project):
        return "case" if project.matter_type == "case" else "subject"

    def _matter_root_node_type(self, project):
        return "case_root" if project.matter_type == "case" else "subject_root"

    def _matter_container_usage(self, project):
        return "cases_container" if project.matter_type == "case" else "subjects_container"

    def ensure_project_directory(self, project):
        if not self._is_legal_matter(project):
            return self.env["dms.directory"]
        directory = project.dms_directory_id or self._get_live_directory(project)
        if directory:
            self._sync_directory_fields(project)
            self.sync_project_access(project)
            return directory
        client_directory = self.ensure_partner_directory(project.partner_id)
        parent_directory = self._ensure_client_container(
            client_directory,
            self._matter_container_usage(project),
        )
        directory = self._directory_create(
            {
                "name": self._project_directory_name(project, parent_directory),
                "parent_id": parent_directory.id,
                "legal_managed": True,
                "legal_node_type": self._matter_root_node_type(project),
                "legal_record_model": project._name,
                "legal_record_id": project.id,
                "res_model": project._name,
                "res_id": project.id,
            }
        )
        for template in self._top_level_templates(self._matter_template_level(project)):
            self._clone_template_tree(template, directory)
        self._record_write(project, {"dms_directory_id": directory.id})
        self.sync_project_access(project)
        return directory

    def relocate_project_directory(self, project):
        if not self._is_legal_matter(project) or not project.dms_directory_id:
            return
        client_directory = self.ensure_partner_directory(project.partner_id)
        target_parent = self._ensure_client_container(
            client_directory,
            self._matter_container_usage(project),
        )
        values = {
            "legal_node_type": self._matter_root_node_type(project),
        }
        if project.dms_directory_id.parent_id != target_parent:
            values["parent_id"] = target_parent.id
            values["name"] = self._project_directory_name(project, target_parent)
        self._directory_write(project.dms_directory_id, values)
        self.sync_project_access(project)

    def _archive_subtree_links(self, root_directory):
        directories = self.env["dms.directory"].sudo().search(
            [("id", "child_of", root_directory.id)],
            order="parent_path, id",
        )
        for directory in directories.filtered(lambda item: item.res_model and item.res_id):
            if "dms_directory_id" in self.env[directory.res_model]._fields:
                record = self.env[directory.res_model].browse(directory.res_id).exists()
                if record:
                    values = {
                        "dms_directory_id": False,
                        "dms_archived_directory_id": directory.id,
                    }
                    self._record_write(record, values)
            self._directory_write(
                directory,
                {
                    "legal_record_model": directory.legal_record_model or directory.res_model,
                    "legal_record_id": directory.legal_record_id or directory.res_id,
                    "res_model": False,
                    "res_id": False,
                    "legal_archived": True,
                },
            )

    def _restore_subtree_links(self, root_directory):
        directories = self.env["dms.directory"].sudo().search(
            [("id", "child_of", root_directory.id)],
            order="parent_path, id",
        )
        for directory in directories.filtered(
            lambda item: item.legal_record_model and item.legal_record_id
        ):
            if directory.legal_record_model not in self.env:
                continue
            record = self.env[directory.legal_record_model].browse(directory.legal_record_id).exists()
            if record and "dms_directory_id" in record._fields:
                self._record_write(
                    record,
                    {
                        "dms_directory_id": directory.id,
                        "dms_archived_directory_id": False,
                    },
                )
            self._directory_write(
                directory,
                {
                    "res_model": directory.legal_record_model,
                    "res_id": directory.legal_record_id,
                    "legal_archived": False,
                },
            )

    def archive_record(self, record):
        directory = record.dms_directory_id or self._get_live_directory(record)
        if not directory:
            return False
        roots = self.ensure_system_roots()
        self._archive_subtree_links(directory)
        self._directory_write(
            directory,
            {
                "parent_id": roots["archive"].id,
                "name": self._child_unique_name(roots["archive"], directory.name),
            },
        )
        self._apply_archived_security(directory)
        if "active" in record._fields:
            self._record_write(record, {"active": False})
        if record._name == "res.partner":
            matter_domain = [
                ("partner_id", "=", record.id),
                ("matter_type", "in", ["case", "subject"]),
                ("is_template", "=", False),
            ]
            matters = self.env["project.project"].sudo().search(matter_domain)
            for matter in matters:
                self._sync_directory_fields(matter)
        elif getattr(record, "partner_id", False):
            self.sync_partner_access(record.partner_id)
        self._sync_directory_fields(record)
        return directory

    def unarchive_record(self, record):
        directory = record.dms_archived_directory_id or self._get_archived_directory(record)
        if not directory:
            return False
        if record._name == "res.partner":
            target_parent = self.ensure_system_roots()["clients"]
        else:
            client_directory = self.ensure_partner_directory(record.partner_id)
            target_parent = self._ensure_client_container(
                client_directory,
                self._matter_container_usage(record),
            )
        self._directory_write(
            directory,
            {
                "parent_id": target_parent.id,
                "name": self._child_unique_name(target_parent, directory.name),
            },
        )
        self._restore_subtree_links(directory)
        if record._name == "res.partner":
            self.sync_partner_access(record)
            matter_domain = [
                ("partner_id", "=", record.id),
                ("matter_type", "in", ["case", "subject"]),
                ("is_template", "=", False),
            ]
            matters = self.env["project.project"].sudo().search(matter_domain)
            self.sync_project_access(matters)
        else:
            self.sync_project_access(record)
        if "active" in record._fields:
            self._record_write(record, {"active": True})
        self._sync_directory_fields(record)
        return directory

    def _partner_button_directory(self, partner, config):
        directory = partner.dms_directory_id or partner.dms_archived_directory_id
        if not directory:
            return self.env["dms.directory"]
        if config.directory_type == "root":
            return directory
        if config.directory_type == "cases":
            return directory.child_directory_ids.filtered(
                lambda item: item.legal_node_type == "cases_container"
            )[:1]
        if config.directory_type == "subjects":
            return directory.child_directory_ids.filtered(
                lambda item: item.legal_node_type == "subjects_container"
            )[:1]
        return self.env["dms.directory"].sudo().search(
            [
                ("id", "child_of", directory.id),
                ("legal_template_id", "=", config.template_id.id),
            ],
            limit=1,
        )

    def _project_button_directory(self, project, config):
        if config.directory_type == "root":
            return project.dms_directory_id or project.dms_archived_directory_id
        client_directory = project.partner_id and (
            project.partner_id.dms_directory_id or project.partner_id.dms_archived_directory_id
        )
        if config.directory_type == "cases" and client_directory:
            return client_directory.child_directory_ids.filtered(
                lambda item: item.legal_node_type == "cases_container"
            )[:1]
        if config.directory_type == "subjects" and client_directory:
            return client_directory.child_directory_ids.filtered(
                lambda item: item.legal_node_type == "subjects_container"
            )[:1]
        directory = project.dms_directory_id or project.dms_archived_directory_id
        if not directory:
            return self.env["dms.directory"]
        return self.env["dms.directory"].sudo().search(
            [
                ("id", "child_of", directory.id),
                ("legal_template_id", "=", config.template_id.id),
            ],
            limit=1,
        )

    def resolve_button_directory(self, record, config):
        if record._name == "res.partner":
            return self._partner_button_directory(record, config)
        if record._name == "project.project":
            return self._project_button_directory(record, config)
        return self.env["dms.directory"]

    def open_button_directory(self, record, config_id):
        config = self.env["dms.smart.button.config"].browse(config_id).exists()
        if not config:
            raise UserError(_("The requested smart button configuration no longer exists."))
        directory = self.resolve_button_directory(record, config)
        if not directory:
            if config.directory_type == "custom":
                raise UserError(
                    _(
                        "This folder does not exist on the current record. Template changes only apply to newly created records."
                    )
                )
            raise UserError(_("The requested legal DMS folder is not available."))
        return {
            "type": "ir.actions.act_window",
            "name": directory.display_name,
            "res_model": "dms.directory",
            "view_mode": "form",
            "view_id": self.env.ref("dms.view_dms_directory_form").id,
            "res_id": directory.id,
            "target": "current",
        }

    def _button_config_domain(self, model_name):
        if model_name == "res.partner":
            return [("target_model", "=", "partner"), ("active", "=", True)]
        return [("target_model", "in", ["case", "subject"]), ("active", "=", True)]

    def _get_smart_button_configs(self, model_name):
        return self.env["dms.smart.button.config"].sudo().search(
            self._button_config_domain(model_name),
            order="sequence, id",
        )

    def inject_smart_buttons(self, arch, model_name):
        configs = self._get_smart_button_configs(model_name)
        if not configs:
            return arch
        document = etree.fromstring(arch.encode())
        button_boxes = document.xpath("//div[@name='button_box']")
        if not button_boxes:
            return arch
        button_box = button_boxes[0]
        if model_name == "project.project" and not document.xpath("//field[@name='matter_type']"):
            sheet = document.xpath("//sheet")
            if sheet:
                sheet[0].insert(0, etree.Element("field", name="matter_type", invisible="1"))
        for config in configs:
            attributes = {
                "name": "action_open_legal_dms_button",
                "type": "object",
                "string": config.name,
                "class": "oe_stat_button",
                "icon": "fa-folder-open-o",
                "context": "{'legal_dms_button_config_id': %d}" % config.id,
                "groups": self._BUTTON_GROUPS,
            }
            if model_name == "project.project":
                attributes["invisible"] = (
                    "matter_type != 'case'"
                    if config.target_model == "case"
                    else "matter_type != 'subject'"
                )
            button_box.append(etree.Element("button", **attributes))
        return etree.tostring(document, encoding="unicode")

    def _smart_button_extension_arch(self, model_name):
        document = etree.Element("data")
        xpath = etree.SubElement(
            document,
            "xpath",
            expr="//div[@name='button_box']",
            position="inside",
        )
        for config in self._get_smart_button_configs(model_name):
            attributes = {
                "name": "action_open_legal_dms_button",
                "type": "object",
                "string": config.name,
                "class": "oe_stat_button",
                "icon": "fa-folder-open-o",
                "context": "{'legal_dms_button_config_id': %d}" % config.id,
                "groups": self._BUTTON_GROUPS,
            }
            if model_name == "project.project":
                attributes["invisible"] = (
                    "matter_type != 'case'"
                    if config.target_model == "case"
                    else "matter_type != 'subject'"
                )
            etree.SubElement(xpath, "button", **attributes)
        return etree.tostring(document, encoding="unicode")

    def sync_smart_button_views(self):
        for model_name, spec in self._SMART_BUTTON_VIEW_SPECS.items():
            self.env.ref(spec["view_xmlid"]).sudo().write(
                {"arch": self._smart_button_extension_arch(model_name)}
            )

    def backfill(self, create_clients=True, create_cases=True, create_subjects=True):
        counts = defaultdict(int)
        if create_clients:
            partners = self.env["res.partner"].sudo().search([("parent_id", "=", False)])
            for partner in partners:
                if self._record_has_any_directory(partner):
                    continue
                self.ensure_partner_directory(partner)
                counts["clients"] += 1
        if create_cases or create_subjects:
            domain = [
                ("is_template", "=", False),
                ("matter_type", "in", ["case", "subject"]),
                ("partner_id", "!=", False),
            ]
            projects = self.env["project.project"].sudo().search(domain)
            for project in projects:
                if project.matter_type == "case" and not create_cases:
                    continue
                if project.matter_type == "subject" and not create_subjects:
                    continue
                if self._record_has_any_directory(project):
                    continue
                self.ensure_project_directory(project)
                counts[project.matter_type] += 1
        return counts
