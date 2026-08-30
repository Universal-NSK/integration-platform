from typing import Sequence, Set

from nashdom_sync.contracts import ExtractedObject
from nashdom_sync.extract.exceptions import SourceDataValidationError


class SourceDataValidator:
    """Проверяет целостность уже нормализованных наборов Extract."""

    def validate_objects(
        self,
        objects: Sequence[ExtractedObject],
        expected_region_ids: Set[int],
    ) -> None:
        """Проверить уникальность объектов и принадлежность запрошенным регионам."""
        seen_ids: Set[int] = set()
        duplicate_ids: Set[int] = set()

        for extracted_object in objects:
            if extracted_object.id in seen_ids:
                duplicate_ids.add(extracted_object.id)
            seen_ids.add(extracted_object.id)

        if duplicate_ids:
            formatted_ids = ", ".join(str(object_id) for object_id in sorted(duplicate_ids))
            raise SourceDataValidationError(
                f"В наборе NashDom повторяются ID объектов: {formatted_ids}"
            )

        unexpected_region_ids = {
            extracted_object.region_id
            for extracted_object in objects
            if extracted_object.region_id not in expected_region_ids
        }
        if unexpected_region_ids:
            formatted_ids = ", ".join(
                str(region_id) for region_id in sorted(unexpected_region_ids)
            )
            raise SourceDataValidationError(
                f"NashDom вернул объекты из незапрошенных регионов: {formatted_ids}"
            )
