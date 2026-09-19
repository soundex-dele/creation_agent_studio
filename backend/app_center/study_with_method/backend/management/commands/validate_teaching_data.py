from django.core.management.base import BaseCommand, CommandError

from ...teaching_data import TeachingDataError, load_teaching_data


class Command(BaseCommand):
    help = "Validate bundled high-school teaching data without writing to the database."

    def handle(self, *args, **options):
        try:
            bundle = load_teaching_data()
        except TeachingDataError as exc:
            raise CommandError(str(exc)) from exc
        points = sum(len(item["points"]) for item in bundle.curricula.values())
        questions = sum(
            len(point["questions"])
            for item in bundle.curricula.values()
            for point in item["points"].values()
        )
        self.stdout.write(self.style.SUCCESS(
            f"Teaching data {bundle.manifest['data_version']} is valid: "
            f"{points} knowledge points, {questions} questions."
        ))
