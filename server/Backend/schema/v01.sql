-- v01: Post classification table for NetspiderHSI 2.0
-- Run after v00.sql. Domains (url, non_empty_text) are already defined in v00.sql.

create table if not exists post_classifications (
    id             serial primary key,
    source_table   non_empty_text not null,
    link           url not null,
    city_or_region non_empty_text not null,
    rule_score     float check (rule_score >= 0 and rule_score <= 100),
    llm_score      float check (llm_score  >= 0 and llm_score  <= 100),
    final_score    float check (final_score >= 0 and final_score <= 100),
    llm_reasoning  text,
    bucket         integer check (bucket in (1, 2, 3)),
    review_status  varchar(32) not null default 'pending'
                       check (review_status in (
                           'pending', 'confirmed_risky', 'cleared', 'marked_safe'
                       )),
    reviewer_notes text,
    reviewed_at    timestamp without time zone,
    reviewed_by    varchar(128),
    classified_at  timestamp without time zone not null default now(),
    unique (source_table, link, city_or_region)
);

create index if not exists idx_pc_bucket_status
    on post_classifications (bucket, review_status);

create index if not exists idx_pc_source
    on post_classifications (source_table, link, city_or_region);
