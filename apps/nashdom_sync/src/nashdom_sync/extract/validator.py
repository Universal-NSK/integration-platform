from typing import Dict, Sequence, Set

from nashdom_sync.contracts import (
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
)
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
            formatted_ids = ", ".join(str(region_id) for region_id in sorted(unexpected_region_ids))
            raise SourceDataValidationError(
                f"NashDom вернул объекты из незапрошенных регионов: {formatted_ids}"
            )

    def validate_developers(
        self,
        developers: Sequence[ExtractedDeveloper],
        expected_developer_ids: Set[int],
    ) -> None:
        """Проверить точное соответствие набора запрошенным ID застройщиков."""
        seen_ids: Set[int] = set()
        duplicate_ids: Set[int] = set()

        for developer in developers:
            if developer.id in seen_ids:
                duplicate_ids.add(developer.id)
            seen_ids.add(developer.id)

        if duplicate_ids:
            formatted_ids = ", ".join(str(developer_id) for developer_id in sorted(duplicate_ids))
            raise SourceDataValidationError(
                f"В наборе NashDom повторяются ID застройщиков: {formatted_ids}"
            )

        unexpected_ids = seen_ids - expected_developer_ids
        if unexpected_ids:
            formatted_ids = ", ".join(str(developer_id) for developer_id in sorted(unexpected_ids))
            raise SourceDataValidationError(
                f"NashDom вернул незапрошенных застройщиков: {formatted_ids}"
            )

        missing_ids = expected_developer_ids - seen_ids
        if missing_ids:
            formatted_ids = ", ".join(str(developer_id) for developer_id in sorted(missing_ids))
            raise SourceDataValidationError(
                f"NashDom не вернул запрошенных застройщиков: {formatted_ids}"
            )

    def validate_company_groups(
        self,
        company_groups: Sequence[ExtractedCompanyGroup],
        expected_company_group_ids: Set[int],
    ) -> None:
        """Проверить точное соответствие набора запрошенным ID групп компаний."""
        seen_ids: Set[int] = set()
        duplicate_ids: Set[int] = set()

        for company_group in company_groups:
            if company_group.id in seen_ids:
                duplicate_ids.add(company_group.id)
            seen_ids.add(company_group.id)

        if duplicate_ids:
            formatted_ids = ", ".join(
                str(company_group_id) for company_group_id in sorted(duplicate_ids)
            )
            raise SourceDataValidationError(
                f"В наборе NashDom повторяются ID групп компаний: {formatted_ids}"
            )

        unexpected_ids = seen_ids - expected_company_group_ids
        if unexpected_ids:
            formatted_ids = ", ".join(
                str(company_group_id) for company_group_id in sorted(unexpected_ids)
            )
            raise SourceDataValidationError(
                f"NashDom вернул незапрошенные группы компаний: {formatted_ids}"
            )

        missing_ids = expected_company_group_ids - seen_ids
        if missing_ids:
            formatted_ids = ", ".join(
                str(company_group_id) for company_group_id in sorted(missing_ids)
            )
            raise SourceDataValidationError(
                f"NashDom не вернул запрошенные группы компаний: {formatted_ids}"
            )

    def validate_company_group_consistency(
        self,
        objects: Sequence[ExtractedObject],
        developers: Sequence[ExtractedDeveloper],
    ) -> None:
        """Сверить только одновременно известные связи с группой компаний."""
        object_group_ids: Dict[int, Set[int]] = {}
        for extracted_object in objects:
            if extracted_object.company_group_id is None:
                continue
            object_group_ids.setdefault(extracted_object.developer_id, set()).add(
                extracted_object.company_group_id
            )

        conflicting_object_groups = {
            developer_id: group_ids
            for developer_id, group_ids in object_group_ids.items()
            if len(group_ids) > 1
        }
        if conflicting_object_groups:
            formatted_conflicts = "; ".join(
                f"{developer_id}: {', '.join(str(group_id) for group_id in sorted(group_ids))}"
                for developer_id, group_ids in sorted(conflicting_object_groups.items())
            )
            raise SourceDataValidationError(
                "Объекты одного застройщика ссылаются на разные группы компаний: "
                f"{formatted_conflicts}"
            )

        developer_group_ids = {developer.id: developer.company_group_id for developer in developers}
        for developer_id, group_ids in object_group_ids.items():
            developer_group_id = developer_group_ids.get(developer_id)
            if developer_group_id is None:
                continue

            object_group_id = next(iter(group_ids))
            if object_group_id != developer_group_id:
                raise SourceDataValidationError(
                    f"Застройщик {developer_id} связан с группой {developer_group_id}, "
                    f"а его объекты — с группой {object_group_id}"
                )
