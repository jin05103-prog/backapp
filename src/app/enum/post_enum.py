from enum import Enum

# 게시 상태 (ERD: 게시중, 게시 완료, 게시 불가, 삭제)
class PostStatus(str, Enum):
    POSTING = "POSTING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    DELETED = "DELETED"  # 작성자가 삭제한 글

# 작성자 타입 (ERD: 보호자, 예비맘, 육아맘)
class PostWriterType(str, Enum):
    GUARDIAN = "GUARDIAN"
    EXPECTANT_MOM = "EXPECTANT_MOM"
    PARENTING_MOM = "PARENTING_MOM"

# 게시글 카테고리 (ERD: 임신 이야기, 육아 이야기, 우리 동네, 건강/병원, 살림/추천)
class PostCategory(str, Enum):
    PREGNANCY_STORY = "PREGNANCY_STORY"
    PARENTING_STORY = "PARENTING_STORY"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    HEALTH = "HEALTH"
    LIVELIHOOD = "LIVELIHOOD"