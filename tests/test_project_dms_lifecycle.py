from odoo.addons.base.tests.common import BaseCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestProjectDmsLifecycle(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.storage = cls.env["dms.storage"].create(
            {"name": "Legal matter DMS lifecycle test", "save_type": "database"}
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "legal_dms_structure.legal_dms_storage_id", cls.storage.id
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Matter Directory Client"}
        )

    def _create_matter(self, matter_type, name):
        return self.env["project.project"].create(
            {
                "name": name,
                "partner_id": self.partner.id,
                "matter_type": matter_type,
                "is_template": False,
            }
        )

    def _expected_directory_name(self, project, directory):
        return self.env["legal.dms.service"]._project_directory_name(
            project,
            directory.parent_id,
            current_directory=directory,
        )

    def test_case_and_subject_name_changes_rename_their_directories(self):
        matters = (
            self._create_matter("case", "Original Case Name"),
            self._create_matter("subject", "Original Subject Name"),
        )

        for project in matters:
            with self.subTest(matter_type=project.matter_type):
                directory = project.dms_directory_id
                project.name = f"Renamed {project.matter_type.title()}"

                self.assertEqual(
                    directory.name,
                    self._expected_directory_name(project, directory),
                )
                self.assertIn(project.name, directory.name)

    def test_archived_matter_name_change_renames_its_directory(self):
        project = self._create_matter("case", "Case Before Archive")

        project.active = False
        directory = project.dms_archived_directory_id
        project.name = "Case Renamed While Archived"

        self.assertEqual(
            directory.name,
            self._expected_directory_name(project, directory),
        )
        self.assertIn(project.name, directory.name)

    def test_upgrade_sync_repairs_case_and_subject_directory_names(self):
        matters = (
            self._create_matter("case", "Current Case Name"),
            self._create_matter("subject", "Current Subject Name"),
        )
        service = self.env["legal.dms.service"]
        for project in matters:
            service._directory_write(
                project.dms_directory_id,
                {"name": f"Stale {project.matter_type.title()} Directory"},
            )

        self.assertEqual(service.sync_project_directory_names(), 2)
        for project in matters:
            directory = project.dms_directory_id
            self.assertEqual(
                directory.name,
                self._expected_directory_name(project, directory),
            )
