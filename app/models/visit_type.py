class VisitType:
    GENERAL = 'GENERAL'
    ACADEMIC = 'ACADEMIC'
    OFFICIAL = 'OFFICIAL'
    CONTRACTOR = 'CONTRACTOR'
    VIP = 'VIP'

    ALL = (GENERAL, ACADEMIC, OFFICIAL, CONTRACTOR, VIP)

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.ALL
