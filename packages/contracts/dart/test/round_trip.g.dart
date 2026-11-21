// GENERATED CODE - DO NOT MODIFY BY HAND
// 由 tools/gen_dart_contracts.py 根据 contracts/openapi.yaml 与 contracts/tutor_event.schema.json 生成。要改动请改契约后重新生成。
// dart format off
// ignore_for_file: type=lint

import 'package:tutor_contracts/tutor_contracts.dart';

typedef RoundTrip = Map<String, dynamic> Function(Map<String, dynamic> json);

/// schema 名 → 把一段 JSON 解析成对应类型再序列化回来。
final Map<String, RoundTrip> roundTrips = {
  'ErrorEnvelope': (json) => ErrorEnvelope.fromJson(json).toJson(),
  'ErrorBody': (json) => ErrorBody.fromJson(json).toJson(),
  'DiagnosticRevision': (json) => DiagnosticRevision.fromJson(json).toJson(),
  'DiagnosticCreate': (json) => DiagnosticCreate.fromJson(json).toJson(),
  'DiagnosticScope': (json) => DiagnosticScope.fromJson(json).toJson(),
  'DiagnosticSubmission': (json) => DiagnosticSubmission.fromJson(json).toJson(),
  'DiagnosticItem': (json) => DiagnosticItem.fromJson(json).toJson(),
  'DiagnosticSummary': (json) => DiagnosticSummary.fromJson(json).toJson(),
  'DiagnosticRun': (json) => DiagnosticRun.fromJson(json).toJson(),
  'DiagnosticHistoryPage': (json) => DiagnosticHistoryPage.fromJson(json).toJson(),
  'DiagnosticWorkspace': (json) => DiagnosticWorkspace.fromJson(json).toJson(),
  'Health': (json) => Health.fromJson(json).toJson(),
  'LaunchConfig': (json) => LaunchConfig.fromJson(json).toJson(),
  'RegionOption': (json) => RegionOption.fromJson(json).toJson(),
  'GradeOption': (json) => GradeOption.fromJson(json).toJson(),
  'SubjectOption': (json) => SubjectOption.fromJson(json).toJson(),
  'CurriculumOption': (json) => CurriculumOption.fromJson(json).toJson(),
  'LocalIdentity': (json) => LocalIdentity.fromJson(json).toJson(),
  'LearningPackPdf': (json) => LearningPackPdf.fromJson(json).toJson(),
  'PaperReviewSchedule': (json) => PaperReviewSchedule.fromJson(json).toJson(),
  'PaperReviewScheduleItem': (json) => PaperReviewScheduleItem.fromJson(json).toJson(),
  'LearningPackHistory': (json) => LearningPackHistory.fromJson(json).toJson(),
  'LearningPackItems': (json) => LearningPackItems.fromJson(json).toJson(),
  'LearningPackItem': (json) => LearningPackItem.fromJson(json).toJson(),
  'LearningPackReturnRecord': (json) => LearningPackReturnRecord.fromJson(json).toJson(),
  'LearningPackCorrection': (json) => LearningPackCorrection.fromJson(json).toJson(),
  'LearningPackPhotoOcrRequest': (json) => LearningPackPhotoOcrRequest.fromJson(json).toJson(),
  'LearningPackPhotoOcr': (json) => LearningPackPhotoOcr.fromJson(json).toJson(),
  'LearningPackReturnRequest': (json) => LearningPackReturnRequest.fromJson(json).toJson(),
  'LearningPackRequest': (json) => LearningPackRequest.fromJson(json).toJson(),
  'LearningJobStatus': (json) => LearningJobStatus.fromJson(json).toJson(),
  'PaperReviewPlanItem': (json) => PaperReviewPlanItem.fromJson(json).toJson(),
  'LearningSettings': (json) => LearningSettings.fromJson(json).toJson(),
  'StudentProfile': (json) => StudentProfile.fromJson(json).toJson(),
  'ProfileNotice': (json) => ProfileNotice.fromJson(json).toJson(),
  'ProfileUpdate': (json) => ProfileUpdate.fromJson(json).toJson(),
  'TodayTasks': (json) => TodayTasks.fromJson(json).toJson(),
  'QuestionTopic': (json) => QuestionTopic.fromJson(json).toJson(),
  'QuestionTopicPage': (json) => QuestionTopicPage.fromJson(json).toJson(),
  'StudyTask': (json) => StudyTask.fromJson(json).toJson(),
  'Applicability': (json) => Applicability.fromJson(json).toJson(),
  'QuestionOriginLocation': (json) => QuestionOriginLocation.fromJson(json).toJson(),
  'QuestionProvenance': (json) => QuestionProvenance.fromJson(json).toJson(),
  'QuestionSource': (json) => QuestionSource.fromJson(json).toJson(),
  'KnowledgeRef': (json) => KnowledgeRef.fromJson(json).toJson(),
  'QuestionOption': (json) => QuestionOption.fromJson(json).toJson(),
  'QuestionBlank': (json) => QuestionBlank.fromJson(json).toJson(),
  'QuestionAttachment': (json) => QuestionAttachment.fromJson(json).toJson(),
  'Subquestion': (json) => Subquestion.fromJson(json).toJson(),
  'ExperimentSafety': (json) => ExperimentSafety.fromJson(json).toJson(),
  'DataTableColumn': (json) => DataTableColumn.fromJson(json).toJson(),
  'DataTableCell': (json) => DataTableCell.fromJson(json).toJson(),
  'DataTableRow': (json) => DataTableRow.fromJson(json).toJson(),
  'DataTable': (json) => DataTable.fromJson(json).toJson(),
  'ProofStatement': (json) => ProofStatement.fromJson(json).toJson(),
  'QuestionContent': (json) => QuestionContent.fromJson(json).toJson(),
  'QuestionAssists': (json) => QuestionAssists.fromJson(json).toJson(),
  'QuestionSummary': (json) => QuestionSummary.fromJson(json).toJson(),
  'Question': (json) => Question.fromJson(json).toJson(),
  'QuestionPage': (json) => QuestionPage.fromJson(json).toJson(),
  'SessionCreate': (json) => SessionCreate.fromJson(json).toJson(),
  'StudySession': (json) => StudySession.fromJson(json).toJson(),
  'AttemptCreate': (json) => AttemptCreate.fromJson(json).toJson(),
  'AnswerBlank': (json) => AnswerBlank.fromJson(json).toJson(),
  'AnswerCell': (json) => AnswerCell.fromJson(json).toJson(),
  'AnswerPart': (json) => AnswerPart.fromJson(json).toJson(),
  'AnswerStep': (json) => AnswerStep.fromJson(json).toJson(),
  'AnswerPayload': (json) => AnswerPayload.fromJson(json).toJson(),
  'Stroke': (json) => Stroke.fromJson(json).toJson(),
  'StrokePage': (json) => StrokePage.fromJson(json).toJson(),
  'StrokeDoc': (json) => StrokeDoc.fromJson(json).toJson(),
  'Draft': (json) => Draft.fromJson(json).toJson(),
  'DraftSync': (json) => DraftSync.fromJson(json).toJson(),
  'SubmitRequest': (json) => SubmitRequest.fromJson(json).toJson(),
  'FeedbackItem': (json) => FeedbackItem.fromJson(json).toJson(),
  'Evaluation': (json) => Evaluation.fromJson(json).toJson(),
  'Attempt': (json) => Attempt.fromJson(json).toJson(),
  'DraftCopyCreate': (json) => DraftCopyCreate.fromJson(json).toJson(),
  'DraftCopy': (json) => DraftCopy.fromJson(json).toJson(),
  'QuestionDraftRef': (json) => QuestionDraftRef.fromJson(json).toJson(),
  'QuestionDraftPage': (json) => QuestionDraftPage.fromJson(json).toJson(),
  'SubmitResult': (json) => SubmitResult.fromJson(json).toJson(),
  'SelfCheckPoint': (json) => SelfCheckPoint.fromJson(json).toJson(),
  'ProofReferenceStep': (json) => ProofReferenceStep.fromJson(json).toJson(),
  'SelfCheckMark': (json) => SelfCheckMark.fromJson(json).toJson(),
  'SelfCheckSave': (json) => SelfCheckSave.fromJson(json).toJson(),
  'SelfCheckSummary': (json) => SelfCheckSummary.fromJson(json).toJson(),
  'SelfCheck': (json) => SelfCheck.fromJson(json).toJson(),
  'TutorAction': (json) => TutorAction.fromJson(json).toJson(),
  'TutorStep': (json) => TutorStep.fromJson(json).toJson(),
  'ContentSpanRef': (json) => ContentSpanRef.fromJson(json).toJson(),
  'ResolvedContentSpan': (json) => ResolvedContentSpan.fromJson(json).toJson(),
  'TeachingReferenceLink': (json) => TeachingReferenceLink.fromJson(json).toJson(),
  'TutorEvent': (json) => TutorEvent.fromJson(json).toJson(),
  'TutorEventMeta': (json) => TutorEventMeta.fromJson(json).toJson(),
  'TutorEventPage': (json) => TutorEventPage.fromJson(json).toJson(),
  'ReviewItem': (json) => ReviewItem.fromJson(json).toJson(),
  'ExportSelfCheck': (json) => ExportSelfCheck.fromJson(json).toJson(),
  'ExportReviewHistory': (json) => ExportReviewHistory.fromJson(json).toJson(),
  'ExportLearningSession': (json) => ExportLearningSession.fromJson(json).toJson(),
  'ExportParentAccessLink': (json) => ExportParentAccessLink.fromJson(json).toJson(),
  'ExportParentAccessInvite': (json) => ExportParentAccessInvite.fromJson(json).toJson(),
  'ExportParentAccessRecords': (json) => ExportParentAccessRecords.fromJson(json).toJson(),
  'ExportStoredScan': (json) => ExportStoredScan.fromJson(json).toJson(),
  'StudentMediaExport': (json) => StudentMediaExport.fromJson(json).toJson(),
  'StudentMediaArchiveObject': (json) => StudentMediaArchiveObject.fromJson(json).toJson(),
  'StudentMediaArchiveManifest': (json) => StudentMediaArchiveManifest.fromJson(json).toJson(),
  'ExportModelCall': (json) => ExportModelCall.fromJson(json).toJson(),
  'ExportModelBudgetDay': (json) => ExportModelBudgetDay.fromJson(json).toJson(),
  'ExportModelUsage': (json) => ExportModelUsage.fromJson(json).toJson(),
  'StudentLearningExport': (json) => StudentLearningExport.fromJson(json).toJson(),
  'ReviewState': (json) => ReviewState.fromJson(json).toJson(),
  'ReviewPage': (json) => ReviewPage.fromJson(json).toJson(),
  'ReviewComplete': (json) => ReviewComplete.fromJson(json).toJson(),
  'ReviewCompletion': (json) => ReviewCompletion.fromJson(json).toJson(),
  'RateStat': (json) => RateStat.fromJson(json).toJson(),
  'ProgressBucket': (json) => ProgressBucket.fromJson(json).toJson(),
  'SubjectiveProgress': (json) => SubjectiveProgress.fromJson(json).toJson(),
  'ProgressSummary': (json) => ProgressSummary.fromJson(json).toJson(),
  'MediaReviewConfirmation': (json) => MediaReviewConfirmation.fromJson(json).toJson(),
  'MediaReviewDeclaration': (json) => MediaReviewDeclaration.fromJson(json).toJson(),
  'SchoolMaterialConfirmationRequest': (json) => SchoolMaterialConfirmationRequest.fromJson(json).toJson(),
  'SchoolMaterialConfirmedItem': (json) => SchoolMaterialConfirmedItem.fromJson(json).toJson(),
  'SchoolMaterialConfirmationReceipt': (json) => SchoolMaterialConfirmationReceipt.fromJson(json).toJson(),
  'SchoolMaterialCandidates': (json) => SchoolMaterialCandidates.fromJson(json).toJson(),
  'SchoolMaterialCandidate': (json) => SchoolMaterialCandidate.fromJson(json).toJson(),
  'SchoolMaterialCandidateLocation': (json) => SchoolMaterialCandidateLocation.fromJson(json).toJson(),
  'SchoolMaterialPages': (json) => SchoolMaterialPages.fromJson(json).toJson(),
  'SchoolMaterialPage': (json) => SchoolMaterialPage.fromJson(json).toJson(),
  'SchoolMaterialCorrectionReceipt': (json) => SchoolMaterialCorrectionReceipt.fromJson(json).toJson(),
  'SchoolMaterialPageCorrection': (json) => SchoolMaterialPageCorrection.fromJson(json).toJson(),
  'SchoolMaterialSubmitRequest': (json) => SchoolMaterialSubmitRequest.fromJson(json).toJson(),
  'SchoolMaterialUploadRequest': (json) => SchoolMaterialUploadRequest.fromJson(json).toJson(),
  'SchoolMaterialSource': (json) => SchoolMaterialSource.fromJson(json).toJson(),
  'MediaBlobUpload': (json) => MediaBlobUpload.fromJson(json).toJson(),
  'MediaConfirm': (json) => MediaConfirm.fromJson(json).toJson(),
  'MediaDelete': (json) => MediaDelete.fromJson(json).toJson(),
  'MediaAssetInfo': (json) => MediaAssetInfo.fromJson(json).toJson(),
  'MediaContent': (json) => MediaContent.fromJson(json).toJson(),
  'MediaDeleted': (json) => MediaDeleted.fromJson(json).toJson(),
  'MediaUploadRequest': (json) => MediaUploadRequest.fromJson(json).toJson(),
  'MediaUpload': (json) => MediaUpload.fromJson(json).toJson(),
  'ScanCreate': (json) => ScanCreate.fromJson(json).toJson(),
  'ScanExpression': (json) => ScanExpression.fromJson(json).toJson(),
  'Scan': (json) => Scan.fromJson(json).toJson(),
  'ScanConfirm': (json) => ScanConfirm.fromJson(json).toJson(),
  'ScanConfirmation': (json) => ScanConfirmation.fromJson(json).toJson(),
  'ParentInvite': (json) => ParentInvite.fromJson(json).toJson(),
  'ParentInviteCreate': (json) => ParentInviteCreate.fromJson(json).toJson(),
  'ParentLinkRevoke': (json) => ParentLinkRevoke.fromJson(json).toJson(),
  'ParentInviteRedeem': (json) => ParentInviteRedeem.fromJson(json).toJson(),
  'PendingParentInvite': (json) => PendingParentInvite.fromJson(json).toJson(),
  'ParentLink': (json) => ParentLink.fromJson(json).toJson(),
  'ParentLinks': (json) => ParentLinks.fromJson(json).toJson(),
  'ParentStudent': (json) => ParentStudent.fromJson(json).toJson(),
  'ParentStudents': (json) => ParentStudents.fromJson(json).toJson(),
  'PreviousWeek': (json) => PreviousWeek.fromJson(json).toJson(),
  'PaperWeeklySummary': (json) => PaperWeeklySummary.fromJson(json).toJson(),
  'ParentWeeklySnapshot': (json) => ParentWeeklySnapshot.fromJson(json).toJson(),
  'ParentWeekly': (json) => ParentWeekly.fromJson(json).toJson(),
  'ReviewBatchItem': (json) => ReviewBatchItem.fromJson(json).toJson(),
  'ReviewBatch': (json) => ReviewBatch.fromJson(json).toJson(),
  'ReviewBatchError': (json) => ReviewBatchError.fromJson(json).toJson(),
  'ReviewBatchResultItem': (json) => ReviewBatchResultItem.fromJson(json).toJson(),
  'ReviewBatchResult': (json) => ReviewBatchResult.fromJson(json).toJson(),
  'ReviewDecision': (json) => ReviewDecision.fromJson(json).toJson(),
  'QuestionReviewState': (json) => QuestionReviewState.fromJson(json).toJson(),
  'AdminQuestionSummary': (json) => AdminQuestionSummary.fromJson(json).toJson(),
  'AdminStatusCounts': (json) => AdminStatusCounts.fromJson(json).toJson(),
  'AdminQuestionPage': (json) => AdminQuestionPage.fromJson(json).toJson(),
  'AdminAnswer': (json) => AdminAnswer.fromJson(json).toJson(),
  'AdminVisual': (json) => AdminVisual.fromJson(json).toJson(),
  'AdminTeaching': (json) => AdminTeaching.fromJson(json).toJson(),
  'AdminSolution': (json) => AdminSolution.fromJson(json).toJson(),
  'AdminRegionTag': (json) => AdminRegionTag.fromJson(json).toJson(),
  'AdminQuestionVersion': (json) => AdminQuestionVersion.fromJson(json).toJson(),
  'AdminHistoryEntry': (json) => AdminHistoryEntry.fromJson(json).toJson(),
  'AdminSolutionInput': (json) => AdminSolutionInput.fromJson(json).toJson(),
  'AdminQuestionEdit': (json) => AdminQuestionEdit.fromJson(json).toJson(),
  'AdminQuestionDraft': (json) => AdminQuestionDraft.fromJson(json).toJson(),
  'AdminImportSource': (json) => AdminImportSource.fromJson(json).toJson(),
  'DocImportOptions': (json) => DocImportOptions.fromJson(json).toJson(),
  'DocImportDefaults': (json) => DocImportDefaults.fromJson(json).toJson(),
  'DocImportJobCreate': (json) => DocImportJobCreate.fromJson(json).toJson(),
  'DocImportJobSummary': (json) => DocImportJobSummary.fromJson(json).toJson(),
  'DocImportPage': (json) => DocImportPage.fromJson(json).toJson(),
  'DocImportFile': (json) => DocImportFile.fromJson(json).toJson(),
  'DocImportLocation': (json) => DocImportLocation.fromJson(json).toJson(),
  'DocImportItemError': (json) => DocImportItemError.fromJson(json).toJson(),
  'DocImportCandidate': (json) => DocImportCandidate.fromJson(json).toJson(),
  'DocImportCandidateInput': (json) => DocImportCandidateInput.fromJson(json).toJson(),
  'DocImportJobDetail': (json) => DocImportJobDetail.fromJson(json).toJson(),
  'DocImportJobPage': (json) => DocImportJobPage.fromJson(json).toJson(),
  'DocImportRevision': (json) => DocImportRevision.fromJson(json).toJson(),
  'DocImportUpload': (json) => DocImportUpload.fromJson(json).toJson(),
  'DocImportUploadResult': (json) => DocImportUploadResult.fromJson(json).toJson(),
  'DocImportContent': (json) => DocImportContent.fromJson(json).toJson(),
  'DocImportCandidatesEdit': (json) => DocImportCandidatesEdit.fromJson(json).toJson(),
  'DocImportSubmit': (json) => DocImportSubmit.fromJson(json).toJson(),
  'DocImportBatchItem': (json) => DocImportBatchItem.fromJson(json).toJson(),
  'DocImportBatchResult': (json) => DocImportBatchResult.fromJson(json).toJson(),
  'AdminQuestionImport': (json) => AdminQuestionImport.fromJson(json).toJson(),
  'AdminVersionSnapshot': (json) => AdminVersionSnapshot.fromJson(json).toJson(),
  'AdminQuestionDetail': (json) => AdminQuestionDetail.fromJson(json).toJson(),
};

/// 仅允许按契约省略 optional nullable null；嵌套自由 JSON 保持原样。
const Map<String, dynamic> roundTripMetadata = {
  "ErrorEnvelope": {
    "nullable": [],
    "objects": {
      "error": "ErrorBody"
    },
    "arrays": {}
  },
  "ErrorBody": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticRevision": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticCreate": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticScope": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticSubmission": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticItem": {
    "nullable": [],
    "objects": {
      "question": "QuestionSummary",
      "submission": "DiagnosticSubmission"
    },
    "arrays": {}
  },
  "DiagnosticSummary": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DiagnosticRun": {
    "nullable": [],
    "objects": {
      "scope": "DiagnosticScope",
      "summary": "DiagnosticSummary"
    },
    "arrays": {
      "items": "DiagnosticItem"
    }
  },
  "DiagnosticHistoryPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "DiagnosticRun"
    }
  },
  "DiagnosticWorkspace": {
    "nullable": [],
    "objects": {
      "run": "DiagnosticRun"
    },
    "arrays": {}
  },
  "Health": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LaunchConfig": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "regions": "RegionOption",
      "grades": "GradeOption",
      "subjects": "SubjectOption",
      "curriculum_versions": "CurriculumOption"
    }
  },
  "RegionOption": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "GradeOption": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SubjectOption": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "CurriculumOption": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LocalIdentity": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackPdf": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "PaperReviewSchedule": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "PaperReviewScheduleItem"
    }
  },
  "PaperReviewScheduleItem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackHistory": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackItems": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "LearningPackItem"
    }
  },
  "LearningPackItem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackReturnRecord": {
    "nullable": [],
    "objects": {
      "item": "LearningPackItem"
    },
    "arrays": {}
  },
  "LearningPackCorrection": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackPhotoOcrRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackPhotoOcr": {
    "nullable": [],
    "objects": {
      "item": "LearningPackItem"
    },
    "arrays": {}
  },
  "LearningPackReturnRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningPackRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "LearningJobStatus": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "reviews": "PaperReviewPlanItem"
    }
  },
  "PaperReviewPlanItem": {
    "nullable": [
      "suggested_on",
      "deferred_reason"
    ],
    "objects": {},
    "arrays": {}
  },
  "LearningSettings": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "StudentProfile": {
    "nullable": [
      "learning_settings"
    ],
    "objects": {
      "learning_settings": "LearningSettings"
    },
    "arrays": {
      "notices": "ProfileNotice"
    }
  },
  "ProfileNotice": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ProfileUpdate": {
    "nullable": [
      "learning_settings",
      "grade",
      "exam_year",
      "curriculum_version",
      "display_name"
    ],
    "objects": {
      "learning_settings": "LearningSettings"
    },
    "arrays": {}
  },
  "TodayTasks": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "StudyTask"
    }
  },
  "QuestionTopic": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionTopicPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "QuestionTopic"
    }
  },
  "StudyTask": {
    "nullable": [],
    "objects": {
      "applicability": "Applicability"
    },
    "arrays": {}
  },
  "Applicability": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionOriginLocation": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionProvenance": {
    "nullable": [],
    "objects": {
      "source_snapshot": "QuestionSource"
    },
    "arrays": {
      "origins": "QuestionOriginLocation"
    }
  },
  "QuestionSource": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "KnowledgeRef": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionOption": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionBlank": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionAttachment": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "Subquestion": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "options": "QuestionOption",
      "blanks": "QuestionBlank"
    }
  },
  "ExperimentSafety": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DataTableColumn": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DataTableCell": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DataTableRow": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "cells": "DataTableCell"
    }
  },
  "DataTable": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "columns": "DataTableColumn",
      "rows": "DataTableRow"
    }
  },
  "ProofStatement": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionContent": {
    "nullable": [],
    "objects": {
      "safety": "ExperimentSafety",
      "proof": "ProofStatement"
    },
    "arrays": {
      "options": "QuestionOption",
      "blanks": "QuestionBlank",
      "subquestions": "Subquestion",
      "attachments": "QuestionAttachment",
      "data_tables": "DataTable"
    }
  },
  "QuestionAssists": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionSummary": {
    "nullable": [],
    "objects": {
      "source": "QuestionSource",
      "applicability": "Applicability"
    },
    "arrays": {
      "knowledge": "KnowledgeRef"
    }
  },
  "Question": {
    "nullable": [
      "provenance"
    ],
    "objects": {
      "provenance": "QuestionProvenance",
      "source": "QuestionSource",
      "applicability": "Applicability",
      "content": "QuestionContent",
      "assists": "QuestionAssists"
    },
    "arrays": {
      "knowledge": "KnowledgeRef"
    }
  },
  "QuestionPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "QuestionSummary"
    }
  },
  "SessionCreate": {
    "nullable": [
      "review_item_id",
      "parent_session_id"
    ],
    "objects": {},
    "arrays": {}
  },
  "StudySession": {
    "nullable": [
      "first_submitted_attempt_id"
    ],
    "objects": {},
    "arrays": {}
  },
  "AttemptCreate": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AnswerBlank": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AnswerCell": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AnswerPart": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AnswerStep": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AnswerPayload": {
    "nullable": [
      "text"
    ],
    "objects": {},
    "arrays": {
      "blanks": "AnswerBlank",
      "parts": "AnswerPart",
      "cells": "AnswerCell",
      "steps": "AnswerStep"
    }
  },
  "Stroke": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "StrokePage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "strokes": "Stroke"
    }
  },
  "StrokeDoc": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "pages": "StrokePage"
    }
  },
  "Draft": {
    "nullable": [],
    "objects": {
      "answer": "AnswerPayload",
      "strokes": "StrokeDoc"
    },
    "arrays": {}
  },
  "DraftSync": {
    "nullable": [
      "answer",
      "strokes"
    ],
    "objects": {
      "answer": "AnswerPayload",
      "strokes": "StrokeDoc"
    },
    "arrays": {}
  },
  "SubmitRequest": {
    "nullable": [
      "elapsed_ms"
    ],
    "objects": {
      "answer": "AnswerPayload"
    },
    "arrays": {}
  },
  "FeedbackItem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "Evaluation": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "feedback": "FeedbackItem"
    }
  },
  "Attempt": {
    "nullable": [
      "submission_no",
      "copied_from_attempt_id",
      "copied_from_revision"
    ],
    "objects": {
      "answer": "AnswerPayload",
      "evaluation": "Evaluation"
    },
    "arrays": {}
  },
  "DraftCopyCreate": {
    "nullable": [],
    "objects": {
      "answer": "AnswerPayload",
      "strokes": "StrokeDoc"
    },
    "arrays": {}
  },
  "DraftCopy": {
    "nullable": [],
    "objects": {
      "session": "StudySession",
      "attempt": "Attempt",
      "draft": "Draft"
    },
    "arrays": {}
  },
  "QuestionDraftRef": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "QuestionDraftPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "QuestionDraftRef"
    }
  },
  "SubmitResult": {
    "nullable": [],
    "objects": {
      "attempt": "Attempt",
      "evaluation": "Evaluation",
      "session": "StudySession",
      "review_item": "ReviewItem"
    },
    "arrays": {
      "events": "TutorEvent"
    }
  },
  "SelfCheckPoint": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ProofReferenceStep": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SelfCheckMark": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SelfCheckSave": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "marks": "SelfCheckMark"
    }
  },
  "SelfCheckSummary": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SelfCheck": {
    "nullable": [],
    "objects": {
      "summary": "SelfCheckSummary"
    },
    "arrays": {
      "points": "SelfCheckPoint",
      "reference_cells": "AnswerCell",
      "reference_steps": "ProofReferenceStep",
      "marks": "SelfCheckMark"
    }
  },
  "TutorAction": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "TutorStep": {
    "nullable": [],
    "objects": {
      "session": "StudySession"
    },
    "arrays": {
      "events": "TutorEvent"
    }
  },
  "ContentSpanRef": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ResolvedContentSpan": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "TeachingReferenceLink": {
    "nullable": [],
    "objects": {
      "source_span": "ContentSpanRef"
    },
    "arrays": {}
  },
  "TutorEvent": {
    "nullable": [],
    "objects": {
      "meta": "TutorEventMeta"
    },
    "arrays": {
      "references": "ResolvedContentSpan"
    }
  },
  "TutorEventMeta": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "TutorEventPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "TutorEvent"
    }
  },
  "ReviewItem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportSelfCheck": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "marks": "SelfCheckMark"
    }
  },
  "ExportReviewHistory": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportLearningSession": {
    "nullable": [],
    "objects": {
      "session": "StudySession"
    },
    "arrays": {
      "attempts": "Attempt",
      "drafts": "Draft",
      "self_checks": "ExportSelfCheck",
      "events": "TutorEvent"
    }
  },
  "ExportParentAccessLink": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportParentAccessInvite": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportParentAccessRecords": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "links": "ExportParentAccessLink",
      "invites": "ExportParentAccessInvite"
    }
  },
  "ExportStoredScan": {
    "nullable": [],
    "objects": {
      "scan": "Scan"
    },
    "arrays": {}
  },
  "StudentMediaExport": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "StudentMediaArchiveObject": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "StudentMediaArchiveManifest": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "objects": "StudentMediaArchiveObject"
    }
  },
  "ExportModelCall": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportModelBudgetDay": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ExportModelUsage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "calls": "ExportModelCall",
      "budget_days": "ExportModelBudgetDay"
    }
  },
  "StudentLearningExport": {
    "nullable": [
      "stored_scan_records"
    ],
    "objects": {
      "model_usage": "ExportModelUsage",
      "parent_access_records": "ExportParentAccessRecords",
      "diagnostic_workspace": "DiagnosticWorkspace",
      "profile": "StudentProfile"
    },
    "arrays": {
      "stored_scan_records": "ExportStoredScan",
      "diagnostic_runs": "DiagnosticRun",
      "sessions": "ExportLearningSession",
      "reviews": "ReviewItem",
      "review_history": "ExportReviewHistory"
    }
  },
  "ReviewState": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ReviewPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "ReviewItem"
    }
  },
  "ReviewComplete": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ReviewCompletion": {
    "nullable": [],
    "objects": {
      "review_item": "ReviewItem"
    },
    "arrays": {}
  },
  "RateStat": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ProgressBucket": {
    "nullable": [],
    "objects": {
      "independent": "RateStat",
      "assisted": "RateStat"
    },
    "arrays": {}
  },
  "SubjectiveProgress": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ProgressSummary": {
    "nullable": [],
    "objects": {
      "independent": "RateStat",
      "assisted": "RateStat",
      "hint_dependency": "RateStat",
      "retest_success": "RateStat",
      "variant_transfer": "RateStat",
      "subjective": "SubjectiveProgress"
    },
    "arrays": {
      "by_subject": "ProgressBucket",
      "by_answer_mode": "ProgressBucket",
      "by_difficulty": "ProgressBucket"
    }
  },
  "MediaReviewConfirmation": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaReviewDeclaration": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialConfirmationRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "SchoolMaterialConfirmedItem"
    }
  },
  "SchoolMaterialConfirmedItem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialConfirmationReceipt": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialCandidates": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "confirmed_items": "SchoolMaterialConfirmedItem",
      "items": "SchoolMaterialCandidate"
    }
  },
  "SchoolMaterialCandidate": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "locations": "SchoolMaterialCandidateLocation"
    }
  },
  "SchoolMaterialCandidateLocation": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialPages": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "pages": "SchoolMaterialPage"
    }
  },
  "SchoolMaterialPage": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialCorrectionReceipt": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialPageCorrection": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialSubmitRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialUploadRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "SchoolMaterialSource": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaBlobUpload": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaConfirm": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaDelete": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaAssetInfo": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaContent": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaDeleted": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaUploadRequest": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "MediaUpload": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ScanCreate": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ScanExpression": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "Scan": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "expressions": "ScanExpression"
    }
  },
  "ScanConfirm": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "expressions": "ScanExpression"
    }
  },
  "ScanConfirmation": {
    "nullable": [],
    "objects": {
      "scan": "Scan"
    },
    "arrays": {}
  },
  "ParentInvite": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentInviteCreate": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentLinkRevoke": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentInviteRedeem": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "PendingParentInvite": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentLink": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentLinks": {
    "nullable": [],
    "objects": {
      "pending_invite": "PendingParentInvite"
    },
    "arrays": {
      "links": "ParentLink"
    }
  },
  "ParentStudent": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ParentStudents": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "ParentStudent"
    }
  },
  "PreviousWeek": {
    "nullable": [],
    "objects": {
      "independent": "RateStat"
    },
    "arrays": {}
  },
  "PaperWeeklySummary": {
    "nullable": [],
    "objects": {
      "independent": "RateStat",
      "assisted": "RateStat"
    },
    "arrays": {}
  },
  "ParentWeeklySnapshot": {
    "nullable": [],
    "objects": {
      "report": "ParentWeekly"
    },
    "arrays": {}
  },
  "ParentWeekly": {
    "nullable": [
      "paper"
    ],
    "objects": {
      "paper": "PaperWeeklySummary",
      "independent": "RateStat",
      "assisted": "RateStat",
      "hint_dependency": "RateStat",
      "retest_success": "RateStat",
      "previous_week": "PreviousWeek"
    },
    "arrays": {
      "by_subject": "ProgressBucket"
    }
  },
  "ReviewBatchItem": {
    "nullable": [
      "comment",
      "solution_kinds"
    ],
    "objects": {},
    "arrays": {}
  },
  "ReviewBatch": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "ReviewBatchItem"
    }
  },
  "ReviewBatchError": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "ReviewBatchResultItem": {
    "nullable": [],
    "objects": {
      "state": "QuestionReviewState",
      "error": "ReviewBatchError"
    },
    "arrays": {}
  },
  "ReviewBatchResult": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "ReviewBatchResultItem"
    }
  },
  "ReviewDecision": {
    "nullable": [
      "comment"
    ],
    "objects": {},
    "arrays": {}
  },
  "QuestionReviewState": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminQuestionSummary": {
    "nullable": [],
    "objects": {
      "source": "QuestionSource"
    },
    "arrays": {}
  },
  "AdminStatusCounts": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminQuestionPage": {
    "nullable": [],
    "objects": {
      "status_counts": "AdminStatusCounts"
    },
    "arrays": {
      "items": "AdminQuestionSummary"
    }
  },
  "AdminAnswer": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminVisual": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminTeaching": {
    "nullable": [],
    "objects": {
      "visual": "AdminVisual"
    },
    "arrays": {
      "reference_links": "TeachingReferenceLink"
    }
  },
  "AdminSolution": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminRegionTag": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminQuestionVersion": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminHistoryEntry": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminSolutionInput": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "AdminQuestionEdit": {
    "nullable": [
      "comment"
    ],
    "objects": {
      "content": "QuestionContent",
      "answer": "AdminAnswer",
      "teaching": "AdminTeaching"
    },
    "arrays": {
      "solutions": "AdminSolutionInput"
    }
  },
  "AdminQuestionDraft": {
    "nullable": [
      "comment"
    ],
    "objects": {
      "content": "QuestionContent",
      "answer": "AdminAnswer",
      "teaching": "AdminTeaching"
    },
    "arrays": {
      "solutions": "AdminSolutionInput"
    }
  },
  "AdminImportSource": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportOptions": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportDefaults": {
    "nullable": [],
    "objects": {
      "source": "AdminImportSource"
    },
    "arrays": {}
  },
  "DocImportJobCreate": {
    "nullable": [],
    "objects": {
      "defaults": "DocImportDefaults"
    },
    "arrays": {}
  },
  "DocImportJobSummary": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportPage": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportFile": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "pages": "DocImportPage"
    }
  },
  "DocImportLocation": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportItemError": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportCandidate": {
    "nullable": [],
    "objects": {
      "payload": "AdminQuestionImport",
      "error": "DocImportItemError"
    },
    "arrays": {
      "locations": "DocImportLocation"
    }
  },
  "DocImportCandidateInput": {
    "nullable": [],
    "objects": {
      "payload": "AdminQuestionImport"
    },
    "arrays": {
      "locations": "DocImportLocation"
    }
  },
  "DocImportJobDetail": {
    "nullable": [],
    "objects": {
      "job": "DocImportJobSummary",
      "defaults": "DocImportDefaults"
    },
    "arrays": {
      "files": "DocImportFile",
      "candidates": "DocImportCandidate"
    }
  },
  "DocImportJobPage": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "DocImportJobSummary"
    }
  },
  "DocImportRevision": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportUpload": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportUploadResult": {
    "nullable": [],
    "objects": {
      "job": "DocImportJobSummary",
      "file": "DocImportFile"
    },
    "arrays": {}
  },
  "DocImportContent": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportCandidatesEdit": {
    "nullable": [],
    "objects": {},
    "arrays": {
      "items": "DocImportCandidateInput"
    }
  },
  "DocImportSubmit": {
    "nullable": [],
    "objects": {},
    "arrays": {}
  },
  "DocImportBatchItem": {
    "nullable": [],
    "objects": {
      "error": "DocImportItemError"
    },
    "arrays": {}
  },
  "DocImportBatchResult": {
    "nullable": [],
    "objects": {
      "job": "DocImportJobSummary"
    },
    "arrays": {
      "items": "DocImportBatchItem"
    }
  },
  "AdminQuestionImport": {
    "nullable": [],
    "objects": {
      "source": "AdminImportSource",
      "question": "AdminQuestionDraft"
    },
    "arrays": {}
  },
  "AdminVersionSnapshot": {
    "nullable": [
      "provenance"
    ],
    "objects": {
      "provenance": "QuestionProvenance",
      "content": "QuestionContent",
      "answer": "AdminAnswer",
      "teaching": "AdminTeaching"
    },
    "arrays": {
      "solutions": "AdminSolution"
    }
  },
  "AdminQuestionDetail": {
    "nullable": [
      "provenance"
    ],
    "objects": {
      "provenance": "QuestionProvenance",
      "source": "QuestionSource",
      "content": "QuestionContent",
      "answer": "AdminAnswer",
      "teaching": "AdminTeaching"
    },
    "arrays": {
      "solutions": "AdminSolution",
      "knowledge": "KnowledgeRef",
      "region_tags": "AdminRegionTag",
      "versions": "AdminQuestionVersion",
      "history": "AdminHistoryEntry"
    }
  }
};

/// 按事件类型把 payload 过一遍对应的类型；不认识的类型返回 null。
Map<String, dynamic>? payloadRoundTrip(TutorEvent event) => switch (event.type) {
      TutorEventType.diagnosis => event.diagnosis.toJson(),
      TutorEventType.hint => event.hint.toJson(),
      TutorEventType.standard => event.standard.toJson(),
      TutorEventType.fast => event.fast.toJson(),
      TutorEventType.visual => event.visual.toJson(),
      TutorEventType.ask => event.ask.toJson(),
      TutorEventType.notice => event.notice.toJson(),
      TutorEventType.uncertainty => event.uncertainty.toJson(),
      TutorEventType.fallback => event.fallback.toJson(),
      TutorEventType.$unknown => null,
    };
