from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestLegalDmsStructure(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["legal.dms.service"]
        cls.directory_model = cls.env["dms.directory"]
        cls.storage = cls.env["dms.storage"].create(
            {
                "name": "Legal DMS Test Storage",
                "save_type": "database",
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "legal_dms_structure.legal_dms_storage_id",
            cls.storage.id,
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "ps_partner_code_sequence.auto_generate_partner_sequence",
            True,
        )
        cls.service.ensure_system_roots(cls.storage)
        cls.staff_user_a = new_test_user(
            cls.env,
            login="legal-dms-staff-a",
            groups="legal_dms_structure.group_legal_dms_staff",
        )
        cls.staff_user_b = new_test_user(
            cls.env,
            login="legal-dms-staff-b",
            groups="legal_dms_structure.group_legal_dms_staff",
        )

    def _create_client(self, name, **extra_vals):
        vals = {"name": name}
        vals.update(extra_vals)
        return self.env["res.partner"].create(vals)

    def _create_matter(self, partner, matter_type, user, name):
        return self.env["project.project"].create(
            {
                "name": name,
                "partner_id": partner.id,
                "matter_type": matter_type,
                "user_id": user.id,
            }
        )

    def test_client_template_applies_only_to_new_clients(self):
        client_a = self._create_client("Client A")
        self.assertTrue(client_a.dms_directory_id)
        self.assertIn(client_a.partner_sequence, client_a.dms_directory_id.name)
        child_names_a = client_a.dms_directory_id.child_directory_ids.mapped("name")
        self.assertIn("Personal Papers", child_names_a)
        self.assertIn("Cases", child_names_a)
        self.assertIn("Subjects", child_names_a)
        self.assertEqual(child_names_a.count("Cases"), 1)
        self.assertEqual(child_names_a.count("Subjects"), 1)
        self.assertNotIn("Cases(1)", child_names_a)
        self.assertNotIn("Subjects(1)", child_names_a)

        template = self.env.ref(
            "legal_dms_structure.dms_directory_template_client_personal_papers"
        )
        template.name = "Identity Papers"

        client_b = self._create_client("Client B")
        child_names_b = client_b.dms_directory_id.child_directory_ids.mapped("name")
        self.assertIn("Personal Papers", child_names_a)
        self.assertNotIn("Identity Papers", child_names_a)
        self.assertIn("Identity Papers", child_names_b)

    def test_matter_directories_and_security_are_isolated(self):
        client = self._create_client("Client Security")
        case = self._create_matter(
            client,
            "case",
            self.staff_user_a,
            "Litigation Matter",
        )
        subject = self._create_matter(
            client,
            "subject",
            self.staff_user_b,
            "Advisory Matter",
        )

        case_dir = case.dms_directory_id
        subject_dir = subject.dms_directory_id
        self.assertEqual(case_dir.parent_id.legal_node_type, "cases_container")
        self.assertEqual(subject_dir.parent_id.legal_node_type, "subjects_container")
        self.assertIn(case.sequence_code, case_dir.name)
        self.assertIn(subject.sequence_code, subject_dir.name)

        client_group = self.service._get_record_access_group(client)
        case_group = self.service._get_record_access_group(case)
        subject_group = self.service._get_record_access_group(subject)

        self.assertTrue(self.staff_user_a in client_group.users)
        self.assertTrue(self.staff_user_b in client_group.users)
        self.assertEqual(case_dir.group_ids, case_group)
        self.assertEqual(subject_dir.group_ids, subject_group)
        self.assertFalse(case_dir.inherit_group_ids)
        self.assertFalse(subject_dir.inherit_group_ids)
        self.assertNotIn(subject_group, case_dir.complete_group_ids)
        self.assertNotIn(case_group, subject_dir.complete_group_ids)
        self.assertIn(case_group, case_dir.child_directory_ids[:1].complete_group_ids)
        self.assertIn(subject_group, subject_dir.child_directory_ids[:1].complete_group_ids)

    def test_manual_create_inside_managed_tree_is_blocked(self):
        client = self._create_client("Client Guard")
        case = self._create_matter(
            client,
            "case",
            self.staff_user_a,
            "Guarded Case",
        )

        with self.assertRaises(UserError):
            self.directory_model.with_user(self.staff_user_a).create(
                {
                    "name": "Manual Folder",
                    "parent_id": case.dms_directory_id.id,
                }
            )

    def test_archive_and_restore_matter_directory(self):
        client = self._create_client("Client Archive")
        case = self._create_matter(
            client,
            "case",
            self.staff_user_a,
            "Archive Case",
        )
        live_directory = case.dms_directory_id

        case.action_archive_legal_dms()
        case = self.env["project.project"].browse(case.id)
        archive_root = self.service.ensure_system_roots()["archive"]
        self.assertFalse(case.dms_directory_id)
        self.assertTrue(case.dms_archived_directory_id)
        self.assertTrue(case.dms_archived_directory_id.legal_archived)
        self.assertEqual(case.dms_archived_directory_id.parent_id, archive_root)
        self.assertFalse(
            self.directory_model.with_user(self.staff_user_a).search_count(
                [("id", "=", case.dms_archived_directory_id.id)]
            )
        )

        case.action_unarchive_legal_dms()
        case = self.env["project.project"].browse(case.id)
        self.assertTrue(case.dms_directory_id)
        self.assertFalse(case.dms_archived_directory_id)
        self.assertEqual(case.dms_directory_id.parent_id.legal_node_type, "cases_container")
        self.assertEqual(case.dms_directory_id.id, live_directory.id)

    def test_backfill_is_idempotent(self):
        client = self.env["res.partner"].with_context(skip_legal_dms_auto_create=True).create(
            {"name": "Client Backfill"}
        )
        case = self.env["project.project"].with_context(
            skip_legal_dms_auto_create=True
        ).create(
            {
                "name": "Backfill Case",
                "partner_id": client.id,
                "matter_type": "case",
                "user_id": self.staff_user_a.id,
            }
        )

        first_run = self.service.backfill()
        second_run = self.service.backfill()

        self.assertGreaterEqual(first_run["clients"], 1)
        self.assertGreaterEqual(first_run["case"], 1)
        self.assertEqual(second_run["clients"], 0)
        self.assertEqual(second_run["case"], 0)
        self.assertTrue(client.dms_directory_id)
        self.assertTrue(case.dms_directory_id)
        child_names = client.dms_directory_id.child_directory_ids.mapped("name")
        self.assertEqual(child_names.count("Cases"), 1)
        self.assertEqual(child_names.count("Subjects"), 1)
        self.assertNotIn("Cases(1)", child_names)
        self.assertNotIn("Subjects(1)", child_names)

    def test_ensure_partner_directory_reuses_legacy_container_names(self):
        client = self.env["res.partner"].with_context(skip_legal_dms_auto_create=True).create(
            {"name": "Client Legacy Containers"}
        )
        roots = self.service.ensure_system_roots()
        legacy_directory = self.directory_model.create(
            {
                "name": self.service._partner_directory_name(client, roots["clients"]),
                "parent_id": roots["clients"].id,
                "legal_managed": True,
                "legal_node_type": "client_root",
                "legal_record_model": client._name,
                "legal_record_id": client.id,
                "res_model": client._name,
                "res_id": client.id,
            }
        )
        self.directory_model.create(
            {
                "name": "Cases",
                "parent_id": legacy_directory.id,
                "legal_managed": True,
                "legal_node_type": "client_node",
            }
        )
        self.directory_model.create(
            {
                "name": "Subjects",
                "parent_id": legacy_directory.id,
                "legal_managed": True,
                "legal_node_type": "client_node",
            }
        )

        self.service.ensure_partner_directory(client)
        client.invalidate_recordset()
        child_directories = client.dms_directory_id.child_directory_ids
        child_names = child_directories.mapped("name")
        self.assertEqual(child_names.count("Cases"), 1)
        self.assertEqual(child_names.count("Subjects"), 1)
        self.assertNotIn("Cases(1)", child_names)
        self.assertNotIn("Subjects(1)", child_names)
        self.assertEqual(
            len(child_directories.filtered(lambda directory: directory.legal_node_type == "cases_container")),
            1,
        )
        self.assertEqual(
            len(
                child_directories.filtered(
                    lambda directory: directory.legal_node_type == "subjects_container"
                )
            ),
            1,
        )

    def test_dynamic_smart_buttons_are_injected(self):
        self.service.sync_smart_button_views()
        self.env.flush_all()
        self.env.cr.execute(
            """
            SELECT key, arch_db::text
            FROM ir_ui_view
            WHERE key IN %s
            """,
            [
                (
                    "legal_dms_structure.smart_buttons_partner",
                    "legal_dms_structure.smart_buttons_project",
                )
            ],
        )
        view_arches = dict(self.env.cr.fetchall())
        partner_arch = view_arches["legal_dms_structure.smart_buttons_partner"]
        project_arch = view_arches["legal_dms_structure.smart_buttons_project"]
        self.assertIn('expr=\\"//header\\"', partner_arch)
        self.assertNotIn("button_box", partner_arch)
        self.assertIn("action_open_legal_dms_button", partner_arch)
        self.assertIn("legal_dms_button_config_id", partner_arch)
        self.assertIn("action_open_legal_dms_button", project_arch)
        self.assertIn("matter_type != 'case'", project_arch)
        self.assertIn("matter_type != 'subject'", project_arch)
        self.assertNotIn("button_box", project_arch)

    def test_backfill_restores_missing_directory_fields(self):
        partner = self.env["res.partner"].with_context(skip_legal_dms_auto_create=True).create(
            {"name": "Client Backfill Restore"}
        )
        matter = self.env["project.project"].with_context(
            skip_legal_dms_auto_create=True
        ).create(
            {
                "name": "Matter Backfill Restore",
                "partner_id": partner.id,
                "matter_type": "case",
                "user_id": self.staff_user_a.id,
            }
        )

        self.service.ensure_partner_directory(partner)
        self.service.ensure_project_directory(matter)
        partner_directory = partner.dms_directory_id
        matter_directory = matter.dms_directory_id

        partner.with_context(skip_legal_dms_sync=True).write({"dms_directory_id": False})
        matter.with_context(skip_legal_dms_sync=True).write({"dms_directory_id": False})

        counts = self.service.backfill()

        partner.invalidate_recordset()
        matter.invalidate_recordset()
        self.assertGreaterEqual(counts["clients"], 1)
        self.assertGreaterEqual(counts["case"], 1)
        self.assertEqual(partner.dms_directory_id, partner_directory)
        self.assertEqual(matter.dms_directory_id, matter_directory)

    def test_button_open_does_not_create_missing_directories(self):
        partner = self.env["res.partner"].with_context(skip_legal_dms_auto_create=True).create(
            {"name": "Client No Create"}
        )
        matter = self.env["project.project"].with_context(
            skip_legal_dms_auto_create=True
        ).create(
            {
                "name": "Matter No Create",
                "partner_id": partner.id,
                "matter_type": "case",
                "user_id": self.staff_user_a.id,
            }
        )

        with self.assertRaises(UserError):
            self.service.open_button_directory(
                partner,
                self.env.ref("legal_dms_structure.dms_smart_button_partner_root").id,
            )
        with self.assertRaises(UserError):
            self.service.open_button_directory(
                matter,
                self.env.ref("legal_dms_structure.dms_smart_button_case_root").id,
            )

        self.assertFalse(partner.dms_directory_id)
        self.assertFalse(matter.dms_directory_id)

    def test_button_open_uses_simplified_directory_view(self):
        partner = self._create_client("Client Simple View")
        matter = self._create_matter(
            partner,
            "case",
            self.staff_user_a,
            "Matter Simple View",
        )
        action = self.service.open_button_directory(
            partner,
            self.env.ref("legal_dms_structure.dms_smart_button_partner_root").id,
        )
        matter_action = self.service.open_button_directory(
            matter,
            self.env.ref("legal_dms_structure.dms_smart_button_case_root").id,
        )

        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["target"], "self")
        self.assertIn(
            f"/odoo/contacts/{partner.id}/dms.directory/{partner.dms_directory_id.id}/action-261",
            action["url"],
        )
        self.assertEqual(matter_action["type"], "ir.actions.act_url")
        self.assertEqual(matter_action["target"], "self")
        self.assertIn(
            f"/odoo/projects/{matter.id}/dms.directory/{matter.dms_directory_id.id}/action-261",
            matter_action["url"],
        )
