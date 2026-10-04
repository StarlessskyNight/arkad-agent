;;; arkad.el --- Arkad Agent integration for Emacs -*- lexical-binding: t; -*-

(require 'vterm nil t)

(defgroup arkad nil
  "Arkad Agent integration."
  :group 'tools)

(defcustom arkad-command "arkad-agent"
  "Command used to launch Arkad Agent."
  :type 'string
  :group 'arkad)

;;;###autoload
(defun arkad-ask (prompt)
  "Ask Arkad PROMPT in a vterm buffer."
  (interactive "sAsk Arkad: ")
  (let ((buf (get-buffer-create "*arkad*")))
    (unless (derived-mode-p 'vterm-mode)
      (with-current-buffer buf
        (vterm--internal arkad-command)))
    (with-current-buffer buf
      (vterm-send-string prompt)
      (vterm-send-return)))
  (display-buffer (get-buffer "*arkad*")))

;;;###autoload
(defun arkad-ask-region (begin end)
  "Send the region between BEGIN and END to Arkad."
  (interactive "r")
  (arkad-ask (format "Explain this code:\n%s"
                     (buffer-substring-no-properties begin end))))

;;;###autoload
(defun arkad-toggle-terminal ()
  "Toggle the Arkad vterm window."
  (interactive)
  (let ((buf (get-buffer "*arkad*")))
    (if (and buf (get-buffer-window buf))
        (delete-window (get-buffer-window buf))
      (arkad-ask ""))))

(provide 'arkad)
;;; arkad.el ends here
