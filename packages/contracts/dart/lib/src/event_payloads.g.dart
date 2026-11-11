// GENERATED CODE - DO NOT MODIFY BY HAND
// 由 tools/gen_dart_contracts.py 根据 contracts/tutor_event.schema.json 生成。要改动请改契约后重新生成。
// dart format off
// ignore_for_file: type=lint

import 'models.g.dart';

class SuggestedAction {
  const SuggestedAction({
    required this.action,
    required this.label,
    this.questionId,
    this.knowledgeId,
  });

  final String action;
  final String label;
  final String? questionId;
  final String? knowledgeId;

  factory SuggestedAction.fromJson(Map<String, dynamic> json) => SuggestedAction(
        action: json['action'] as String,
        label: json['label'] as String,
        questionId: json['question_id'] == null ? null : json['question_id'] as String,
        knowledgeId: json['knowledge_id'] == null ? null : json['knowledge_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'action': action,
        'label': label,
        'question_id': questionId,
        'knowledge_id': knowledgeId,
      };
}

class DiagnosisFeedback {
  const DiagnosisFeedback({
    required this.target,
    required this.code,
    required this.message,
  });

  final String target;
  final String code;
  final String message;

  factory DiagnosisFeedback.fromJson(Map<String, dynamic> json) => DiagnosisFeedback(
        target: json['target'] as String,
        code: json['code'] as String,
        message: json['message'] as String,
      );

  Map<String, dynamic> toJson() => {
        'target': target,
        'code': code,
        'message': message,
      };
}

class EventKnowledgeRef {
  const EventKnowledgeRef({
    required this.id,
    required this.code,
    required this.title,
  });

  final String id;
  final String code;
  final String title;

  factory EventKnowledgeRef.fromJson(Map<String, dynamic> json) => EventKnowledgeRef(
        id: json['id'] as String,
        code: json['code'] as String,
        title: json['title'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'code': code,
        'title': title,
      };
}

class SolutionStep {
  const SolutionStep({
    required this.text,
  });

  final String text;

  factory SolutionStep.fromJson(Map<String, dynamic> json) => SolutionStep(
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'text': text,
      };
}

class OptionAnalysis {
  const OptionAnalysis({
    required this.key,
    required this.verdict,
    required this.text,
  });

  final String key;
  final String verdict;
  final String text;

  factory OptionAnalysis.fromJson(Map<String, dynamic> json) => OptionAnalysis(
        key: json['key'] as String,
        verdict: json['verdict'] as String,
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'verdict': verdict,
        'text': text,
      };
}

class DiagnosisPayload {
  const DiagnosisPayload({
    required this.outcome,
    required this.summary,
    required this.feedback,
    required this.knowledge,
    required this.suggestions,
  });

  final String outcome;
  final String summary;
  final List<DiagnosisFeedback> feedback;
  final List<EventKnowledgeRef> knowledge;
  final List<SuggestedAction> suggestions;

  factory DiagnosisPayload.fromJson(Map<String, dynamic> json) => DiagnosisPayload(
        outcome: json['outcome'] as String,
        summary: json['summary'] as String,
        feedback: (json['feedback'] as List<dynamic>).map((e) => DiagnosisFeedback.fromJson(e as Map<String, dynamic>)).toList(),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => EventKnowledgeRef.fromJson(e as Map<String, dynamic>)).toList(),
        suggestions: (json['suggestions'] as List<dynamic>).map((e) => SuggestedAction.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'outcome': outcome,
        'summary': summary,
        'feedback': feedback.map((e) => e.toJson()).toList(),
        'knowledge': knowledge.map((e) => e.toJson()).toList(),
        'suggestions': suggestions.map((e) => e.toJson()).toList(),
      };
}

class HintPayload {
  const HintPayload({
    required this.level,
    required this.totalLevels,
    required this.style,
    required this.text,
    this.concept,
  });

  final int level;
  final int totalLevels;
  final String style;
  final String text;
  final String? concept;

  factory HintPayload.fromJson(Map<String, dynamic> json) => HintPayload(
        level: (json['level'] as num).toInt(),
        totalLevels: (json['total_levels'] as num).toInt(),
        style: json['style'] as String,
        text: json['text'] as String,
        concept: json['concept'] == null ? null : json['concept'] as String,
      );

  Map<String, dynamic> toJson() => {
        'level': level,
        'total_levels': totalLevels,
        'style': style,
        'text': text,
        'concept': concept,
      };
}

class StandardPayload {
  const StandardPayload({
    required this.title,
    required this.steps,
    required this.finalAnswer,
    required this.optionAnalysis,
    required this.keyPoints,
  });

  final String title;
  final List<SolutionStep> steps;
  final String finalAnswer;
  final List<OptionAnalysis> optionAnalysis;
  final List<String> keyPoints;

  factory StandardPayload.fromJson(Map<String, dynamic> json) => StandardPayload(
        title: json['title'] as String,
        steps: (json['steps'] as List<dynamic>).map((e) => SolutionStep.fromJson(e as Map<String, dynamic>)).toList(),
        finalAnswer: json['final_answer'] as String,
        optionAnalysis: (json['option_analysis'] as List<dynamic>).map((e) => OptionAnalysis.fromJson(e as Map<String, dynamic>)).toList(),
        keyPoints: (json['key_points'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'title': title,
        'steps': steps.map((e) => e.toJson()).toList(),
        'final_answer': finalAnswer,
        'option_analysis': optionAnalysis.map((e) => e.toJson()).toList(),
        'key_points': keyPoints,
      };
}

class FastPayload {
  const FastPayload({
    required this.title,
    required this.conditions,
    required this.steps,
    required this.finalAnswer,
    required this.boundary,
    required this.reviewed,
  });

  final String title;
  final List<String> conditions;
  final List<SolutionStep> steps;
  final String finalAnswer;
  final String boundary;
  final bool reviewed;

  factory FastPayload.fromJson(Map<String, dynamic> json) => FastPayload(
        title: json['title'] as String,
        conditions: (json['conditions'] as List<dynamic>).map((e) => e as String).toList(),
        steps: (json['steps'] as List<dynamic>).map((e) => SolutionStep.fromJson(e as Map<String, dynamic>)).toList(),
        finalAnswer: json['final_answer'] as String,
        boundary: json['boundary'] as String,
        reviewed: json['reviewed'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'title': title,
        'conditions': conditions,
        'steps': steps.map((e) => e.toJson()).toList(),
        'final_answer': finalAnswer,
        'boundary': boundary,
        'reviewed': reviewed,
      };
}

class VisualPayload {
  const VisualPayload({
    required this.templateId,
    required this.params,
    required this.caption,
    required this.staticFallback,
  });

  final String templateId;
  final Map<String, double> params;
  final String caption;
  final String staticFallback;

  factory VisualPayload.fromJson(Map<String, dynamic> json) => VisualPayload(
        templateId: json['template_id'] as String,
        params: (json['params'] as Map).map((k, e) => MapEntry(k as String, (e as num).toDouble())),
        caption: json['caption'] as String,
        staticFallback: json['static_fallback'] as String,
      );

  Map<String, dynamic> toJson() => {
        'template_id': templateId,
        'params': params,
        'caption': caption,
        'static_fallback': staticFallback,
      };
}

class AskPayload {
  const AskPayload({
    required this.prompt,
    required this.suggestions,
  });

  final String prompt;
  final List<SuggestedAction> suggestions;

  factory AskPayload.fromJson(Map<String, dynamic> json) => AskPayload(
        prompt: json['prompt'] as String,
        suggestions: (json['suggestions'] as List<dynamic>).map((e) => SuggestedAction.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'prompt': prompt,
        'suggestions': suggestions.map((e) => e.toJson()).toList(),
      };
}

class NoticePayload {
  const NoticePayload({
    required this.code,
    required this.text,
    this.dueAt,
  });

  final String code;
  final String text;
  final DateTime? dueAt;

  factory NoticePayload.fromJson(Map<String, dynamic> json) => NoticePayload(
        code: json['code'] as String,
        text: json['text'] as String,
        dueAt: json['due_at'] == null ? null : DateTime.parse(json['due_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'code': code,
        'text': text,
        'due_at': dueAt?.toUtc().toIso8601String(),
      };
}

class UncertaintyPayload {
  const UncertaintyPayload({
    required this.reasonCode,
    required this.text,
    required this.reviewRequired,
  });

  final String reasonCode;
  final String text;
  final bool reviewRequired;

  factory UncertaintyPayload.fromJson(Map<String, dynamic> json) => UncertaintyPayload(
        reasonCode: json['reason_code'] as String,
        text: json['text'] as String,
        reviewRequired: json['review_required'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'reason_code': reasonCode,
        'text': text,
        'review_required': reviewRequired,
      };
}

class FallbackPayload {
  const FallbackPayload({
    required this.reasonCode,
    required this.text,
    required this.suggestions,
  });

  final String reasonCode;
  final String text;
  final List<SuggestedAction> suggestions;

  factory FallbackPayload.fromJson(Map<String, dynamic> json) => FallbackPayload(
        reasonCode: json['reason_code'] as String,
        text: json['text'] as String,
        suggestions: (json['suggestions'] as List<dynamic>).map((e) => SuggestedAction.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'reason_code': reasonCode,
        'text': text,
        'suggestions': suggestions.map((e) => e.toJson()).toList(),
      };
}

/// 按事件类型把 payload 解析成对应的类型。调用前先看 `type`。
extension TutorEventPayloads on TutorEvent {
  /// `type == diagnosis` 时的 payload。
  DiagnosisPayload get diagnosis => DiagnosisPayload.fromJson(payload);
  /// `type == hint` 时的 payload。
  HintPayload get hint => HintPayload.fromJson(payload);
  /// `type == standard` 时的 payload。
  StandardPayload get standard => StandardPayload.fromJson(payload);
  /// `type == fast` 时的 payload。
  FastPayload get fast => FastPayload.fromJson(payload);
  /// `type == visual` 时的 payload。
  VisualPayload get visual => VisualPayload.fromJson(payload);
  /// `type == ask` 时的 payload。
  AskPayload get ask => AskPayload.fromJson(payload);
  /// `type == notice` 时的 payload。
  NoticePayload get notice => NoticePayload.fromJson(payload);
  /// `type == uncertainty` 时的 payload。
  UncertaintyPayload get uncertainty => UncertaintyPayload.fromJson(payload);
  /// `type == fallback` 时的 payload。
  FallbackPayload get fallback => FallbackPayload.fromJson(payload);
}
