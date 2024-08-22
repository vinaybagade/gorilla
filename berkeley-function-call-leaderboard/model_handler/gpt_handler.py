from openai import OpenAI
import os, time, json, logging
from model_handler.handler import BaseHandler
from model_handler.model_style import ModelStyle
from model_handler.utils import (
    convert_to_tool,
    convert_to_function_call,
    system_prompt_pre_processing,
    user_prompt_pre_processing_chat_model,
    func_doc_language_specific_pre_processing,
    ast_parse,
)
from model_handler.constant import (
    GORILLA_TO_OPENAPI,
    USER_PROMPT_FOR_CHAT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
)


class OpenAIHandler(BaseHandler):
    def __init__(self, model_name, temperature=0.001, top_p=1, max_tokens=1000) -> None:
        super().__init__(model_name, temperature, top_p, max_tokens)
        self.model_style = ModelStyle.OpenAI
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_BASE_URL"), api_key=os.getenv("OPENAI_API_KEY")
        )

    def inference(self, prompt, functions, test_category):
        prompt = augment_prompt_by_languge(prompt, test_category)
        functions = language_specific_pre_processing(functions, test_category)
        message = [{"role": "user", "content": prompt}]
        if type(functions) is not list:
            functions = [functions]

        oai_tool = convert_to_tool(
            functions, GORILLA_TO_OPENAPI, self.model_style, test_category
        )

        logging.debug("Message: %s", str(message))
        logging.debug("Tools: %s", str(oai_tool))
        metadata = {}

        if "FC" not in self.model_name or len(oai_tool) == 0:
            message = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_FOR_CHAT_MODEL,
                },
                {
                    "role": "user",
                    "content": USER_PROMPT_FOR_CHAT_MODEL.format(
                        user_prompt=prompt, functions=str(functions)
                    ),
                },
            ]

            start_time = time.time()
            response = self.client.chat.completions.create(
                messages=message,
                model=self.model_name.replace("-FC", ""),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
            )
            latency = time.time() - start_time
            metadata["input_tokens"] = response.usage.prompt_tokens
            metadata["output_tokens"] = response.usage.completion_tokens
            metadata["latency"] = latency
            result = response.choices[0].message.content
            logging.debug("Response: %s", str(result))
            return result, metadata

        oai_tool = convert_to_tool(
            functions, GORILLA_TO_OPENAPI, self.model_style, test_category
        )
        start_time = time.time()
        response = self.client.chat.completions.create(
            messages=message,
            model=self.model_name.replace("-FC", ""),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            tools=oai_tool,
        )
        latency = time.time() - start_time
        result = response.choices[0].message.content

        if response.choices[0].message.tool_calls:
            result = [
                {func_call.function.name: func_call.function.arguments}
                for func_call in response.choices[0].message.tool_calls
            ]
        logging.debug("Response: %s", str(result))
        metadata["input_tokens"] = response.usage.prompt_tokens
        metadata["output_tokens"] = response.usage.completion_tokens
        metadata["latency"] = latency
        return result, metadata

    def decode_ast(self, result, language="Python"):
        if "FC" not in self.model_name:
            decoded_output = ast_parse(result, language)
        else:
            decoded_output = []
            for invoked_function in result:
                name = list(invoked_function.keys())[0]
                params = json.loads(invoked_function[name])
                decoded_output.append({name: params})
        return decoded_output

    def decode_execute(self, result):
        if "FC" not in self.model_name:
            func = result
            if " " == func[0]:
                func = func[1:]
            if not func.startswith("["):
                func = "[" + func
            if not func.endswith("]"):
                func = func + "]"
            decoded_output = ast_parse(func)
            execution_list = []
            for function_call in decoded_output:
                for key, value in function_call.items():
                    execution_list.append(
                        f"{key}({','.join([f'{k}={repr(v)}' for k, v in value.items()])})"
                    )
            return execution_list
        else:
            function_call = convert_to_function_call(result)
            return function_call
